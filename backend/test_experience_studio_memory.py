import asyncio
import importlib
import json
import sys
import types


def _fresh_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("MONGODB_DISABLE_DRIVER_IMPORT", "true")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DIRECT_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_EXPERIENCE_STUDIO_STORE_PATH", str(tmp_path / "experience_studio_drafts.json"))
    monkeypatch.setenv("PARKPULSE_EXPERIENCE_STUDIO_MEMORY_FALLBACK_PATH", str(tmp_path / "experience_studio_memory_fallback.json"))
    import mongo_memory
    import experience_studio

    mongo_memory = importlib.reload(mongo_memory)
    experience_studio = importlib.reload(experience_studio)
    return experience_studio, mongo_memory


def test_generation_writes_evidence_only_memory_receipt(monkeypatch, tmp_path):
    experience_studio, mongo_memory = _fresh_modules(monkeypatch, tmp_path)

    payload = {
        "templateId": "kid-quest",
        "audience": "kids ages 6 to 10 with caregivers",
        "tone": "curious and warm",
        "constraints": "Use verified venue facts only.",
        "useVenueExperienceData": True,
        "useLlm": False,
    }
    result = asyncio.run(experience_studio.build_experience_studio_payload(payload, None))

    memory = result["memoryPersistence"]
    assert memory["status"] == "stored"
    assert memory["collection"] == "experience_studio_generation_runs"
    assert result["studioCore"]["id"] == "parkpulse_experience_studio_core_v1"
    assert result["draft"]["studioCore"]["coreValues"]
    assert result["creativePrompt"]["studio_core_preset"]["id"] == "parkpulse_experience_studio_core_v1"
    assert result["draft"]["sourceIntegrity"]["usesSeedData"] is False
    rows = mongo_memory.get_latest_memory_documents_fast("experience_studio_generation_runs", 5)
    assert rows
    assert rows[0]["eventType"] == "generation_run"
    assert rows[0]["studioCore"]["id"] == "parkpulse_experience_studio_core_v1"
    assert rows[0]["learningEligible"] is False
    assert rows[0]["learningSource"] == "generation_receipt_only"


def test_saved_draft_and_human_review_write_studio_memory(monkeypatch, tmp_path):
    experience_studio, mongo_memory = _fresh_modules(monkeypatch, tmp_path)

    draft = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "families",
            "tone": "calm",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": {
                "source": "test_export",
                "locations": ["Indoor Launch", "Arcade Zone", "Theater B", "Food Court A", "Food Court B"],
            },
        }
    )
    saved = experience_studio.save_experience_studio_draft({"templateId": "rainy-day", "draft": draft, "actor": "designer"})
    draft_id = saved["draftRecord"]["id"]
    assert saved["memoryPersistence"]["collection"] == "experience_studio_drafts"

    updated = experience_studio.update_experience_studio_draft_status(
        draft_id,
        {"status": "approved", "actor": "reviewer", "note": "Approved route story after review."},
    )
    assert updated["status"] == "updated"
    assert updated["memoryPersistence"]["feedback"]["collection"] == "experience_studio_feedback"

    feedback_rows = mongo_memory.get_latest_memory_documents_fast("experience_studio_feedback", 5)
    assert feedback_rows
    assert feedback_rows[0]["eventType"] == "draft_status_review"
    assert feedback_rows[0]["learningEligible"] is False
    assert feedback_rows[0]["learningSource"] == "human_review_receipt_only"
    assert feedback_rows[0]["learningPolicy"]["humanFeedbackLearningEligible"] is False

    memory = experience_studio.list_experience_studio_memory(limit=5)
    assert memory["status"] == "ready"
    assert memory["learningPolicy"]["presetCoreId"] == "parkpulse_experience_studio_core_v1"
    assert memory["collectionCounts"]["experience_studio_drafts"] >= 1
    assert memory["collectionCounts"]["experience_studio_feedback"] >= 1


def test_studio_core_can_load_from_config_file(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    custom_core = {
        "id": "custom_studio_core",
        "version": "test",
        "mission": "Test configurable Studio Core.",
        "coreValues": ["Comfort first."],
        "reasoningPriorities": ["1. Test priority."],
    }
    core_path = tmp_path / "studio_core.json"
    core_path.write_text(json.dumps(custom_core), encoding="utf-8")
    monkeypatch.setenv("PARKPULSE_EXPERIENCE_STUDIO_CORE_PATH", str(core_path))

    result = asyncio.run(experience_studio.build_experience_studio_payload({"templateId": "rainy-day", "useLlm": False}, None))

    assert result["studioCore"]["id"] == "custom_studio_core"
    assert result["draft"]["studioCore"]["source"] == str(core_path)
    assert result["creativePrompt"]["studio_core_preset"]["coreValues"] == ["Comfort first."]


def test_conversation_plan_creates_generator_ready_brief_without_learning_loop(monkeypatch, tmp_path):
    experience_studio, mongo_memory = _fresh_modules(monkeypatch, tmp_path)
    real_inputs = {
        "source": "approved_profile_export",
        "locations": ["Indoor Launch", "Arcade Zone", "Theater B", "Covered Plaza", "Harbor Treats"],
        "indoorLocations": ["Indoor Launch", "Arcade Zone", "Theater B"],
        "quietLocations": ["Theater B"],
        "accessibleRoutes": ["Step-free route is available between all selected indoor stops."],
        "safetyInstructions": ["Follow posted safety instructions and ask a team member for support."],
        "channelOwners": {
            "guest_app": "Digital product",
            "signage": "Park experience",
            "email": "CRM",
            "staff_cue": "Operations training",
        },
    }

    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Build a rainy-day family journey with indoor stops, calm copy, app/signage/email/staff cues, and optional movement.",
            "useVenueExperienceData": False,
            "realInputs": real_inputs,
        }
    )

    assert plan["status"] == "ready"
    assert plan["mode"] == "experience_studio_conversation_plan"
    assert plan["parsedBrief"]["templateId"] == "rainy-day"
    assert plan["recommendedPlan"]["payload"]["templateId"] == "rainy-day"
    assert plan["recommendedPlan"]["payload"]["audience"] == "mixed family groups"
    assert plan["sourceIntegrity"]["usesSeedData"] is False
    assert plan["studioCore"]["id"] == "parkpulse_experience_studio_core_v1"
    assert plan["memoryPersistence"]["collection"] == "experience_studio_generation_runs"
    assert plan["memoryPersistence"]["status"] == "stored"

    rows = mongo_memory.get_latest_memory_documents_fast("experience_studio_generation_runs", 5)
    assert rows
    assert rows[0]["eventType"] == "conversation_plan"
    assert rows[0]["learningEligible"] is False
    assert rows[0]["learningSource"] == "conversation_plan_receipt_only"

    generated = asyncio.run(experience_studio.build_experience_studio_payload(plan["recommendedPlan"]["payload"], None))
    assert generated["draft"]["creativeBrief"]["seasonalTheme"].startswith("Build a rainy-day family journey")
    assert generated["draft"]["sourceIntegrity"]["usesSeedData"] is False
    package = generated["draft"]["creativePackage"]
    assert package["executiveConcept"]["oneLine"]
    assert package["executiveConcept"]["guestPromise"]
    assert len(package["journeyMap"]) == len(generated["draft"]["route"])
    assert package["staffScript"]["openingLine"]
    assert package["signageSet"]
    assert package["preArrivalEmail"]["subject"]
    assert package["accessibilityReviewPacket"]["mustVerify"]
    assert package["ownerQuestions"]
    reasoning = generated["draft"]["experienceReasoning"]
    assert reasoning["status"] == "ready"
    assert len(reasoning["conceptRoutes"]) >= 2
    assert reasoning["selectedConceptId"]
    assert reasoning["decision"]["whySelected"]
    assert reasoning["decision"]["route"]
    assert reasoning["critiqueAndRevision"]["revisionsApplied"]
    assert reasoning["guestLenses"]
    assert reasoning["conceptRoutes"][0]["scores"]["guestComfort"] >= 0
    assert package["designReasoning"]["selectedConceptId"] == reasoning["selectedConceptId"]
    synthesis = generated["draft"]["creativeSynthesis"]
    assert synthesis["status"] == "ready"
    assert synthesis["selectedConceptName"]
    assert len(synthesis["concepts"]) >= 2
    assert synthesis["copyVariants"]["guestApp"]["headline"]
    assert package["creativeSynthesis"]["selectedConceptId"] == synthesis["selectedConceptId"]
    assert package["sectionDossiers"]
    assert package["routeBlueprint"]
    assert package["channelMatrix"]
    assert package["productionDetail"]["contentCompletenessChecklist"]
    assert package["memoryInfluence"]["authority"] == "retrieval_context_only"
    assert package["sectionCreativeDetails"]["conceptBoard"]["workingTitle"]
    assert package["sectionCreativeDetails"]["routeStoryCards"]
    assert package["memoryApplication"]["status"] in {"active", "not_active"}
    assert package["venueDataGapAnalysis"]["missingForProduction"]
    assert package["studioQualityEval"]["score"] > 0
    assert package["studioQualityEval"]["qaChecklist"]
    assert package["creativePackageVariants"]
    assert len(package["craftArtifacts"]["samples"]) >= 3
    assert package["reviewAgentReview"]["agentId"] == "experience_studio_review_agent"
    assert generated["draft"]["experienceReviewAgent"]["agentId"] == "experience_studio_review_agent"
    route_copy = [stop["guestCopy"] for stop in generated["draft"]["route"]]
    assert any("Start dry" in copy for copy in route_copy)
    assert any("short reset" in copy or "quiet middle beat" in copy for copy in route_copy)


def test_profile_backed_generation_uses_venue_pattern_and_copy_voice(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    draft = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": venue_data["realInputs"],
        }
    )
    package = draft["creativePackage"]

    assert package["venuePattern"]["id"] == "rainy_day"
    assert draft["creativeSynthesis"]["selectedConceptName"] in {"Dry Dragon Trail", "Lantern Rain Reset", "Indoor Choice Loop"}
    assert package["executiveConcept"]["name"] == draft["creativeSynthesis"]["selectedConceptName"]
    assert package["copyVoice"]["selectedTerms"]
    assert "one seated reset" in package["venuePattern"]["mustInclude"]
    assert "optional route" in package["copyVoice"]["approvedPhrases"]
    assert "rain" in package["copyVoice"]["thematicLexicon"]
    assert package["venuePattern"]["channelRules"]["guest_app"]
    assert venue_data["realInputs"]["profileIntelligence"]["experienceRules"]["routePatterns"]["rainy_day"]["preferredStops"]
    assert package["venueDataGapAnalysis"]["status"] == "synthetic_complete_review_required"
    assert package["venueDataGapAnalysis"]["missingForProduction"] == ["real venue source feed instead of approved synthetic profile"]
    assert "synthetic current-options and attraction status snapshot" in package["venueDataGapAnalysis"]["filledForSyntheticDemo"]
    assert package["venueDataGapAnalysis"]["syntheticOperatingCoverage"]["signagePlacements"] >= 4


def test_generation_uses_approved_finished_work_memory_without_feedback_loop(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    first = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": venue_data["realInputs"],
        }
    )
    saved = experience_studio.save_experience_studio_draft({"templateId": "rainy-day", "draft": first, "actor": "designer"})
    draft_id = saved["draftRecord"]["id"]
    approved = experience_studio.update_experience_studio_draft_status(
        draft_id,
        {"status": "approved", "actor": "reviewer", "note": "Approved finished pattern for future Studio context."},
    )
    assert approved["status"] == "updated"

    second = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": venue_data["realInputs"],
        }
    )
    memory = second["finishedWorkMemory"]
    package_memory = second["creativePackage"]["memoryInfluence"]

    assert memory["status"] == "ready"
    assert memory["matchedExamples"][0]["draftId"] == draft_id
    assert memory["matchedExamples"][0]["selectedConceptName"]
    assert package_memory["usedForGeneration"] is True
    assert package_memory["authority"] == "retrieval_context_only"
    assert second["creativePackage"]["memoryApplication"]["usedForGeneration"] is True
    assert second["creativePackage"]["memoryApplication"]["visibleChanges"]
    assert any(
        dossier.get("section") == "memory"
        for dossier in second["creativePackage"]["sectionDossiers"]
    )
    assert second["creativePackage"]["productionDetail"]["measurementPlan"][1]["learningUse"] == "finished-work pattern after approval"
    assert second["studioCore"]["id"] == "parkpulse_experience_studio_core_v1"


def test_human_promoted_learning_rule_influences_future_generation(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    first = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": venue_data["realInputs"],
        }
    )
    saved = experience_studio.save_experience_studio_draft({"templateId": "rainy-day", "draft": first, "actor": "designer"})
    draft_id = saved["draftRecord"]["id"]

    blocked = experience_studio.promote_experience_studio_learning_rule(
        draft_id,
        {"candidateId": "complete_package_shape", "actor": "reviewer"},
    )
    assert blocked["status"] == "blocked"

    approved = experience_studio.update_experience_studio_draft_status(
        draft_id,
        {"status": "approved", "actor": "reviewer", "note": "Approved finished pattern for rule promotion."},
    )
    assert approved["status"] == "updated"

    promoted = experience_studio.promote_experience_studio_learning_rule(
        draft_id,
        {"candidateId": "complete_package_shape", "actor": "reviewer", "note": "Promote package completeness rule."},
    )
    assert promoted["status"] == "promoted"
    assert promoted["rule"]["approvalStatus"] == "approved"
    assert promoted["rule"]["learningSource"] == "human_promoted_finished_work_rule"
    assert promoted["rule"]["learningEligible"] is False
    craft_promoted = experience_studio.promote_experience_studio_learning_rule(
        draft_id,
        {"candidateId": "creative_craft_examples", "actor": "creative_lead", "note": "Accepted one creative lead sample as reusable craft guidance."},
    )
    assert craft_promoted["status"] == "promoted"
    assert "creative_craft" in craft_promoted["rule"]["tags"]
    assert "craft sample" in craft_promoted["rule"]["lesson"].lower()

    rules = experience_studio.list_experience_studio_learning_rules(limit=5)
    assert rules["count"] >= 2

    second = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": venue_data["realInputs"],
        }
    )
    rule_context = second["approvedLearningRules"]
    package_rules = second["creativePackage"]["approvedRuleInfluence"]

    assert rule_context["status"] == "ready"
    assert rule_context["ruleCount"] >= 2
    assert rule_context["learningBoundary"] == "Rules are human-promoted from finished work and can shape generation, but they cannot override Venue Profile facts, route locks, banned claims, or review gates."
    assert any("creative_craft" in rule.get("tags", []) for rule in rule_context["rules"])
    assert package_rules["usedForGeneration"] is True
    assert package_rules["authority"] == "human_promoted_rules_only"
    assert second["creativeSynthesis"]["learningRuleInfluence"]["usedForGeneration"] is True
    assert any("creative_craft" in rule.get("tags", []) for rule in second["creativeSynthesis"]["learningRuleInfluence"]["rules"])
    assert any("accepted craft" in item.lower() or "creative lead-approved craft" in item.lower() for item in second["creativePackage"]["memoryApplication"]["visibleChanges"])
    assert "approvedRulesApplied" in second["creativePackage"]["memoryApplication"]
    assert any(
        dossier.get("section") == "approved rules"
        for dossier in second["creativePackage"]["sectionDossiers"]
    )

    demoted = experience_studio.update_experience_studio_learning_rule(
        promoted["rule"]["id"],
        {"status": "demoted", "actor": "reviewer", "note": "Rule no longer needed."},
    )
    assert demoted["status"] == "updated"
    craft_demoted = experience_studio.update_experience_studio_learning_rule(
        craft_promoted["rule"]["id"],
        {"status": "demoted", "actor": "creative_lead", "note": "Craft sample rule no longer needed."},
    )
    assert craft_demoted["status"] == "updated"

    third = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": venue_data["realInputs"],
        }
    )
    assert third["approvedLearningRules"]["status"] == "no_approved_rules"


def test_section_revision_agent_returns_before_after_and_qa_delta(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    draft = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": venue_data["realInputs"],
        }
    )

    revised = experience_studio.revise_experience_studio_section(
        {
            "draft": draft,
            "sectionId": "staff_script",
            "feedback": "Make the staff script less operational and keep accessibility language plain.",
        }
    )

    assert revised["status"] == "revised"
    assert revised["sectionId"] == "staff_script"
    assert revised["beforeSection"]
    assert revised["afterSection"]
    assert revised["qaDelta"]["after"] >= revised["qaDelta"]["before"]
    assert revised["reviewAgent"]["agentId"] == "experience_studio_review_agent"
    assert revised["draft"]["experienceReviewAgent"]["reviewMode"] == "post_revision_review"
    assert "less operational" in json.dumps(revised["afterSection"], default=str).lower() or "guest support" in json.dumps(revised["afterSection"], default=str).lower()


def test_llm_creative_pass_polishes_selected_synthesis_without_control_authority(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)

    async def fake_generate_gemini_json_hard_timeout(*_args, **_kwargs):
        return {
            "transport": "fake",
            "text": json.dumps(
                {
                    "route": [
                        {"stop": "Indoor Launch", "purpose": "Invite families into the Dry Dragon Trail with a clear first dry marker.", "guestCopy": "1. Begin the Dry Dragon Trail at Indoor Launch, then choose the next dry marker when your group is ready.", "staffNote": "Name the route and keep the first choice optional."},
                        {"stop": "Arcade Zone", "purpose": "Turn the rain delay into a flexible choice pause.", "guestCopy": "2. Use Arcade Zone as a choice pause: play, watch, or continue when the next marker feels right.", "staffNote": "Point out the quieter side path before guests decide."},
                        {"stop": "Theater B", "purpose": "Give the route a seated warm pause.", "guestCopy": "3. Take the warm pause at Theater B, check current options, and decide whether to continue or close the route early.", "staffNote": "Offer the seated reset without implying a showtime or seat guarantee."},
                        {"stop": "Food Court A", "purpose": "Make the food stop a comfortable family reset.", "guestCopy": "4. Pause at Food Court A for a snack, restroom choice, or simple regroup before the close.", "staffNote": "Keep the direction short and point to the approved next marker."},
                        {"stop": "Food Court B", "purpose": "Close with a covered regroup and current-options handoff.", "guestCopy": "5. Close at Food Court B, regroup, and check the app for current next options.", "staffNote": "End with the current-options phrase, not an availability promise."},
                    ],
                    "messages": [
                        {"channel": "Guest app", "copy": "Dry Dragon Trail starts at Indoor Launch and keeps the rainy-day path optional from the first marker."},
                        {"channel": "Signage", "copy": "Dry marker starts here. Follow the next marker when ready."},
                        {"channel": "Pre-arrival email", "copy": "Look for the Dry Dragon Trail if rain changes the day. It gives your group indoor-first choices and a clear regroup."},
                        {"channel": "Staff cue", "copy": "Offer the route as optional, name the next marker, and remind guests to check the app for current options."},
                    ],
                    "creative_synthesis": {
                        "selectedConceptId": "dry_dragon_trail",
                        "selectedConceptName": "Dry Dragon Trail",
                        "selectedConcept": {
                            "id": "dry_dragon_trail",
                            "name": "Dry Dragon Trail",
                            "positioning": "A named rainy-day route that makes Indoor Launch feel like the first dry spark, then gives families calm choices instead of pressure.",
                            "guestPromise": "Families can turn rain into a clear indoor-first path with a seated pause, flexible exits, and current-options language.",
                            "whyItWorks": "It gives the content team a memorable route name while preserving verified stops, optional movement, and owner review.",
                        },
                        "copyVariants": {
                            "guestApp": {"headline": "Dry Dragon Trail", "body": "Start at Indoor Launch, follow the dry markers, and pause whenever your group needs a reset.", "microcopy": "check the app for current options"},
                            "signage": [
                                {"placement": "Indoor Launch", "headline": "Dry marker starts", "body": "Follow the next marker when ready."},
                                {"placement": "Food Court B", "headline": "Regroup here", "body": "Choose the next option in the app."},
                            ],
                            "email": {"subject": "Try the Dry Dragon Trail", "previewText": "A rainy-day route with optional indoor-first choices.", "body": "Before arrival, look for Dry Dragon Trail. It starts at Indoor Launch and closes with a clear regroup at Food Court B."},
                            "staffCue": {"opening": "Offer Dry Dragon Trail as an optional rainy-day route.", "transition": "Point to the next dry marker and remind guests they can pause.", "boundary": "check the app for current options"},
                        },
                        "rewriteStrategy": {"useMoreOf": ["dry spark", "warm pause"], "preserve": ["verified stop names", "optional movement"], "avoid": ["availability promises"]},
                    },
                    "creative_rationale": ["The selected concept now carries stronger channel copy without changing route authority."],
                    "review_questions": ["Can Digital Product use Dry Dragon Trail as the app headline?"],
                }
            ),
        }

    fake_module = types.SimpleNamespace(generate_gemini_json_hard_timeout=fake_generate_gemini_json_hard_timeout)
    monkeypatch.setitem(sys.modules, "gemini_hard_timeout", fake_module)

    result = asyncio.run(
        experience_studio.build_experience_studio_payload(
            {
                "templateId": "rainy-day",
                "audience": "mixed family groups",
                "tone": "calm, plain, respectful",
                "constraints": "Use verified venue facts only.",
                "useVenueExperienceData": True,
                "useLlm": True,
            },
            None,
        )
    )

    draft = result["draft"]
    synthesis = draft["creativeSynthesis"]
    package = draft["creativePackage"]
    assert result["llm"]["status"] == "ready"
    assert draft["llmCreativePass"]["routeAccepted"] is True
    assert draft["llmCreativePass"]["synthesisAcceptedFields"] >= 8
    assert synthesis["selectedConceptId"] == "dry_dragon_trail"
    assert synthesis["selectedConceptName"] == "Dry Dragon Trail"
    assert synthesis["selectedConcept"]["guestPromise"].startswith("Families can turn rain")
    assert synthesis["llmPolish"]["status"] == "merged"
    assert package["executiveConcept"]["guestPromise"].startswith("Families can turn rain")
    assert package["creativeSynthesis"]["copyVariants"]["guestApp"]["body"].startswith("Start at Indoor Launch")
    assert result["controlBoundary"]["llm_control_authority"] is False


def test_llm_creative_pass_rejects_banned_synthesis_claims(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    real_inputs = venue_data["realInputs"]
    draft = experience_studio._draft_from_payload(
        {
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, plain, respectful",
            "constraints": "Use verified venue facts only.",
            "venueExperienceDataUsed": True,
            "realInputs": real_inputs,
        }
    )
    original_body = draft["creativeSynthesis"]["copyVariants"]["guestApp"]["body"]
    generated = {
        "creative_synthesis": {
            "selectedConceptId": draft["creativeSynthesis"]["selectedConceptId"],
            "selectedConceptName": draft["creativeSynthesis"]["selectedConceptName"],
            "selectedConcept": {
                "id": draft["creativeSynthesis"]["selectedConceptId"],
                "name": draft["creativeSynthesis"]["selectedConceptName"],
                "guestPromise": "Guaranteed no wait and always available dry access.",
            },
            "copyVariants": {
                "guestApp": {
                    "headline": "Dry Dragon Trail",
                    "body": "Guaranteed no wait on this always available rainy-day route.",
                    "microcopy": "priority access is included",
                }
            },
        }
    }

    merged = experience_studio._merge_llm_creative_pass(draft, generated, real_inputs, "rainy-day", "Use verified venue facts only.", {"source": "test"})
    polish = merged["creativeSynthesis"]["llmPolish"]

    assert merged["creativeSynthesis"]["copyVariants"]["guestApp"]["body"] == original_body
    assert polish["acceptedFields"] == 1
    assert any("blocked_claim" in item["reason"] for item in polish["rejectedFields"])
    assert "Guaranteed no wait" not in json.dumps(merged["creativePackage"], default=str)


def test_conversation_plan_uses_profile_patterns_segments_and_channel_targets(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a rainy-day family journey for mixed-age family groups with app, signage, email, and staff cue artifacts.",
            "useVenueExperienceData": False,
            "realInputs": venue_data["realInputs"],
        }
    )

    planner = plan["plannerIntelligence"]
    assert planner["routePattern"]["id"] == "rainy_day"
    assert "dry start" in planner["routePattern"]["recommendedArc"]
    assert planner["targetSegment"]["id"] in {"mixed_age_family_groups", "families_with_strollers", "rainy_day_parties"}
    assert planner["channelTargets"] == ["guest_app", "signage", "email", "staff_cue"]
    assert planner["profileEvidence"]["hasRoutePattern"] is True
    assert plan["conceptOptions"][0]["profileFit"]["routePatternId"] == "rainy_day"
    assert plan["recommendedPlan"]["payload"]["planningProfile"]["routePattern"]["id"] == "rainy_day"
    assert any(item["id"] == "route_pattern" for item in plan["clarifyingQuestions"])


def test_conversation_plan_uses_followup_answers_to_refine_recommendation(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    real_inputs = {
        "source": "approved_profile_export",
        "locations": ["Indoor Launch", "Arcade Zone", "Theater B", "Covered Plaza", "Harbor Treats"],
        "indoorLocations": ["Indoor Launch", "Arcade Zone", "Theater B"],
        "quietLocations": ["Theater B"],
        "accessibleRoutes": ["Step-free route is available between all selected indoor stops."],
        "safetyInstructions": ["Follow posted safety instructions and ask a team member for support."],
        "channelOwners": {"guest_app": "Digital product", "signage": "Park experience", "email": "CRM", "staff_cue": "Operations training"},
    }

    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a rainy-day guest journey.",
            "history": [
                {"role": "assistant", "content": "What should this experience improve?"},
                {"role": "designer", "content": "Success metric is pre-arrival clarity. Guest commitment is a short optional moment. Approved comfort claims are indoor stop, covered path, seating, and step-free access. Review owner is CRM."},
            ],
            "useVenueExperienceData": False,
            "realInputs": real_inputs,
        }
    )

    assert plan["parsedBrief"]["successMetric"] == "pre-arrival clarity"
    assert plan["parsedBrief"]["guestCommitment"] == "a short optional moment"
    assert "step-free access" in plan["parsedBrief"]["approvedComfortClaims"]
    assert "success_metric" in plan["answeredQuestionIds"]
    assert "guest_commitment" in plan["answeredQuestionIds"]
    assert plan["recommendedOptionId"] == "low_friction_channel_pack"
    payload = plan["recommendedPlan"]["payload"]
    assert payload["walkingPace"] == "compact"
    assert "Success metric: pre-arrival clarity." in payload["constraints"]
    assert "Approved comfort claims:" in payload["constraints"]


def test_approved_learning_rules_deduplicate_semantic_duplicates(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)

    duplicate_rows = [
        {
            "id": "rule_a",
            "approvalStatus": "approved",
            "rule": "Keep the rainy-day package complete: route, channels, staff cue, review gates.",
            "scope": {"templateId": "rainy-day", "audience": "families", "channels": ["guest_app", "email"]},
            "tags": ["complete_package", "rainy-day"],
            "guardrails": ["Do not override venue profile facts."],
        },
        {
            "id": "rule_b",
            "approvalStatus": "approved",
            "rule": "Keep   the rainy-day package complete: route, channels, staff cue, review gates.",
            "scope": {"templateId": "rainy-day", "audience": "families", "channels": ["email", "guest_app"]},
            "tags": ["rainy-day", "complete_package"],
            "guardrails": ["Do not override venue profile facts."],
        },
        {
            "id": "rule_c",
            "approvalStatus": "approved",
            "rule": "Use short pre-arrival copy before guest arrival.",
            "scope": {"templateId": "rainy-day", "audience": "families", "channels": ["email"]},
            "tags": ["pre_arrival"],
            "guardrails": ["Do not invent weather guarantees."],
        },
    ]
    monkeypatch.setattr(experience_studio, "_latest_studio_memory", lambda collection, limit: duplicate_rows)

    active = experience_studio._active_learning_rules("rainy-day", "families", ["guest_app", "email"])
    context = experience_studio._learning_rule_context("rainy-day", "families", ["guest_app", "email"])

    assert [item["id"] for item in active] == ["rule_a", "rule_c"]
    assert context["ruleCount"] == 2
    assert len(context["appliedRules"]) == 2


def test_full_studio_lifecycle_writes_audit_receipts(monkeypatch, tmp_path):
    experience_studio, mongo_memory = _fresh_modules(monkeypatch, tmp_path)
    real_inputs = {
        "source": "test_export",
        "locations": ["Indoor Launch", "Arcade Zone", "Theater B", "Food Court A", "Food Court B"],
        "indoorLocations": ["Indoor Launch", "Arcade Zone", "Theater B"],
        "quietLocations": ["Theater B"],
        "accessibleRoutes": ["Step-free route is available between all selected indoor stops."],
        "safetyInstructions": ["Follow posted safety instructions and ask a team member for support."],
        "channelOwners": {
            "guest_app": "Digital product",
            "signage": "Park experience",
            "email": "CRM",
            "staff_cue": "Operations training",
        },
    }
    generated = asyncio.run(
        experience_studio.build_experience_studio_payload(
            {
                "templateId": "rainy-day",
                "audience": "families",
                "tone": "calm",
                "constraints": "Use verified venue facts only.",
                "useLlm": False,
                "realInputs": real_inputs,
            },
            None,
        )
    )
    assert generated["draft"]["sourceIntegrity"]["readyForHandoff"] is True

    saved = experience_studio.save_experience_studio_draft({"templateId": "rainy-day", "draft": generated["draft"], "actor": "designer"})
    draft_id = saved["draftRecord"]["id"]
    updated = experience_studio.update_experience_studio_draft_content(
        draft_id,
        {"draft": generated["draft"], "actor": "designer", "note": "Copy tuned while preserving source facts."},
    )
    approved = experience_studio.update_experience_studio_draft_status(
        draft_id,
        {"status": "approved", "actor": "reviewer", "note": "Approved as audit receipt, not a learning signal."},
    )
    handoff = experience_studio.create_experience_studio_handoff(draft_id, {"actor": "experience_studio", "note": "Demo handoff."})
    handoff_id = handoff["handoff"]["id"]
    handoff_review = experience_studio.update_experience_studio_handoff_status(
        handoff_id,
        {"status": "accepted_for_channel_owner_review", "actor": "command_center", "note": "Accepted for owner review."},
    )

    assert saved["status"] == "saved"
    assert updated["status"] == "updated"
    assert approved["status"] == "updated"
    assert handoff["status"] == "created"
    assert handoff_review["status"] == "updated"

    feedback_rows = mongo_memory.get_latest_memory_documents_fast("experience_studio_feedback", 10)
    revision_rows = mongo_memory.get_latest_memory_documents_fast("experience_studio_revision_events", 10)
    assert any(row["eventType"] == "draft_status_review" for row in feedback_rows)
    assert any(row["eventType"] == "handoff_status_review" for row in feedback_rows)
    assert all(row.get("learningEligible") is False for row in feedback_rows[:2])
    assert any(row["eventType"] == "content_updated" for row in revision_rows)
    assert any(row["eventType"] == "handoff_created" for row in revision_rows)


def test_experience_studio_role_capabilities_are_declared():
    from park_role_access import authorize_role_action

    assert authorize_role_action("ops_team", "use_experience_studio")["allowed"] is True
    assert authorize_role_action("ops_team", "review_experience_studio")["allowed"] is True
    assert authorize_role_action("ml_ops_admin", "manage_experience_studio_core")["allowed"] is True
    assert authorize_role_action("customer", "use_experience_studio")["allowed"] is False
