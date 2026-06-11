import asyncio
import importlib
import json
import sys
import types


def _fresh_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("MONGODB_DISABLE_DRIVER_IMPORT", "true")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DIRECT_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "false")
    monkeypatch.setenv("PARKPULSE_EXPERIENCE_STUDIO_USE_LLM", "false")
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

    plan_payload = {
        **plan["recommendedPlan"]["payload"],
        "plannerContext": {
            "source": "conversation_plan",
            "designerRequest": "Create a rainy-day family journey with verified indoor stops.",
            "recommendedPlanLabel": plan["recommendedPlan"]["label"],
            "recommendedPayload": plan["recommendedPlan"]["payload"],
            "planStatus": plan["status"],
        },
    }
    generated = asyncio.run(experience_studio.build_experience_studio_payload(plan_payload, None))
    assert generated["draft"]["creativeBrief"]["seasonalTheme"].startswith("Build a rainy-day family journey")
    assert generated["draft"]["sourceIntegrity"]["usesSeedData"] is False
    package = generated["draft"]["creativePackage"]
    assert generated["draft"]["plannerContext"]["source"] == "conversation_plan"
    assert generated["draft"]["plannerContext"]["recommendedPlanLabel"] == plan["recommendedPlan"]["label"]
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
    event_team = package["eventTeamMarketingPackage"]
    assert event_team["mode"] == "event_team_marketing_package_v1"
    assert event_team["publishAuthority"] is False
    assert event_team["eventBrief"]["eventName"]
    assert len(event_team["workstreams"]) >= 5
    assert {item["id"] for item in event_team["deliverables"]} >= {"web_hero", "pre_arrival_email", "onsite_signage", "visual_key_art"}
    assert event_team["executionBoundary"]
    assert package["productionDetail"]["contentCompletenessChecklist"]
    assert package["memoryInfluence"]["authority"] == "retrieval_context_only"
    assert package["sectionCreativeDetails"]["conceptBoard"]["workingTitle"]
    assert package["sectionCreativeDetails"]["routeStoryCards"]
    assert package["memoryApplication"]["status"] in {"active", "not_active"}
    assert package["venueDataGapAnalysis"]["missingForProduction"]
    assert package["studioQualityEval"]["score"] > 0
    assert package["studioQualityEval"]["qaChecklist"]
    venue_reflection = package["studioQualityEval"]["venueReflection"]
    assert venue_reflection["score"] > 0
    assert venue_reflection["gateSummary"]["passed"] >= 8
    assert {item["id"] for item in venue_reflection["dimensions"]} >= {
        "source_depth",
        "spatial_model",
        "attractions_shows",
        "dining_care_services",
        "guest_segment_fit",
        "accessibility_safety",
        "operations_currentness",
        "weather_timing",
        "channel_signage_governance",
        "brand_localization",
        "learning_feed_boundaries",
        "experience_rules",
    }
    assert package["studioQualityEval"]["scores"]["venueReflection"] == venue_reflection["score"]
    assert package["creativePackageVariants"]
    assert len(package["craftArtifacts"]["samples"]) >= 3
    vertex = package["vertexModelOrchestration"]
    assert vertex["mode"] == "vertex_ai_multi_model_enrichment_v1"
    assert vertex["slotCount"] == 6
    assert "providerReadiness" in vertex
    assert "cannot publish" in vertex["boundary"].lower()
    slots = {slot["id"]: slot for slot in vertex["slots"]}
    assert set(slots) == {
        "planner_reasoning",
        "package_writer",
        "reviewer_critic",
        "embedding_memory",
        "image_concept_board",
        "video_preview",
    }
    assert slots["embedding_memory"]["prompt"]["chunks"][2]["text"]
    assert slots["image_concept_board"]["prompt"]["imagePrompts"]
    assert slots["video_preview"]["prompt"]["videoPrompts"]
    assert all(slot["llmControlsPublishOrOperations"] is False for slot in slots.values())
    assert package["reviewAgentReview"]["agentId"] == "experience_studio_review_agent"
    assert generated["draft"]["experienceReviewAgent"]["agentId"] == "experience_studio_review_agent"
    route_copy = [stop["guestCopy"] for stop in generated["draft"]["route"]]
    assert any("Start dry" in copy for copy in route_copy)
    assert any("short reset" in copy or "quiet middle beat" in copy for copy in route_copy)


def test_conversation_plan_text_overrides_stale_template_for_chinese_new_year(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)

    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a chinese new year festival plan that run for a month",
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "calm, helpful, upbeat",
            "useVenueExperienceData": True,
        }
    )

    assert plan["parsedBrief"]["templateId"] == "festival-plan"
    assert plan["recommendedPlan"]["payload"]["templateId"] == "festival-plan"
    assert plan["recommendedPlan"]["label"] == "Lantern Wishes festival concept"
    assert "Chinese New Year" in plan["recommendedPlan"]["payload"]["seasonalTheme"] or "festival" in plan["recommendedPlan"]["payload"]["seasonalTheme"].lower()

    generated = asyncio.run(experience_studio.build_experience_studio_payload(plan["recommendedPlan"]["payload"], None))
    package = generated["draft"]["creativePackage"]
    visible_output = {
        "title": generated["draft"]["title"],
        "creativeBrief": generated["draft"]["creativeBrief"],
        "route": generated["draft"]["route"],
        "messages": generated["draft"]["messages"],
        "concept": package["executiveConcept"],
        "signage": package["signageSet"],
        "email": package["preArrivalEmail"],
        "staffScript": package["staffScript"],
        "experienceBeats": package["experienceBeats"],
        "routeBlueprint": package["routeBlueprint"],
    }
    assert generated["draft"]["title"] == "Festival Experience Plan"
    assert "rainy" not in json.dumps(visible_output, default=str).lower()
    assert package["executiveConcept"]["name"] == "Lantern Wishes Festival Month"
    assert "month" in package["preArrivalEmail"]["body"].lower()
    assert package["contentCreationModel"]["mode"] == "evidence_backed_package_content_v1"
    assert package["eventTeamNarrative"]["creativeTerritory"].startswith("Warm lantern festival")
    assert len(package["programCalendar"]) == 3
    assert len(package["eventTeamMarketingPackage"]["executionPlan"]) == 3
    assert len(package["eventTeamMarketingPackage"]["approvalMatrix"]) >= 5
    assert package["eventTeamMarketingPackage"]["executiveNarrative"]["marketingAngle"].startswith("A month of optional lantern")
    assert "Create a chinese new year" not in package["executiveConcept"]["guestPromise"]
    assert "Create a chinese new year" not in generated["draft"]["route"][0]["guestCopy"]
    assert "launch, discovery, and finale" in package["executiveConcept"]["oneLine"]
    assert package["eventTeamMarketingPackage"]["eventBrief"]["format"] == "Month-long seasonal festival"
    assert package["eventTeamMarketingPackage"]["eventBrief"]["runShape"] == "Kickoff, discovery, finale"
    assert any(item["team"] == "Creative and brand" for item in package["eventTeamMarketingPackage"]["workstreams"])
    assert len(package["signageSet"]) >= 3
    assert any("festival cue" in sign["body"].lower() or "wish" in sign["body"].lower() for sign in package["signageSet"])
    assert any("Launch" == beat["beat"] for beat in package["experienceBeats"])
    assert "optional festival-month path" in package["staffScript"]["openingLine"]


def test_conversation_plan_autohydrates_active_venue_profile_by_default(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import activate_synthetic_venue_export

    activated = activate_synthetic_venue_export("pytest")
    assert activated["status"] == "imported"

    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a chinese new year festival plan that run for a month",
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "festive, respectful, clear",
        }
    )

    assert plan["parsedBrief"]["templateId"] == "festival-plan"
    assert plan["sourceIntegrity"]["realInputCount"] > 10
    assert plan["retrievalEvidence"]["status"] == "ready"
    assert len(plan["retrievalEvidence"]["retrievedEvidence"]) >= 8
    assert {tool["id"] for tool in plan["planningTools"]} >= {"retrieval_evidence", "agent_workflow"}
    assert plan["recommendedPlan"]["payload"]["realInputs"]["locations"]


def test_expanded_template_coverage_routes_free_text_to_new_categories(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    expected = {
        "Create a holiday seasonal overlay with photo moments": "seasonal-overlay",
        "Design a food festival tasting trail": "food-festival",
        "Build an instagram photo moment route": "photo-moment-route",
        "Create an accessible family day plan": "accessibility-family-day",
        "Plan a teen night out route": "teen-night-out",
        "Create a first-time visitor orientation journey": "first-time-visitor",
        "Design a date night route": "date-night",
        "Create an education field trip plan": "education-field-trip",
        "Write post-incident recovery copy after a disruption": "post-incident-recovery-copy",
        "Create a retail merch quest": "retail-merch-quest",
    }

    assert len(experience_studio.TEMPLATES) == 19
    for message, template_id in expected.items():
        plan = experience_studio.build_experience_studio_conversation_plan(
            {
                "message": message,
                "templateId": "rainy-day",
                "audience": "mixed guest groups",
                "tone": "clear, warm, reviewable",
                "useVenueExperienceData": False,
                "realInputs": venue_data["realInputs"],
            }
        )
        assert plan["parsedBrief"]["templateId"] == template_id
        assert plan["recommendedPlan"]["payload"]["templateId"] == template_id
        assert plan["retrievalEvidence"]["retrievedEvidence"]
        assert {tool["id"] for tool in plan["planningTools"]} >= {"retrieval_evidence", "agent_workflow"}


def test_new_template_generates_named_content_package(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a date night route with scenic photo moments and a relaxed close",
            "templateId": "rainy-day",
            "audience": "adult couples",
            "tone": "warm, relaxed, tasteful",
            "useVenueExperienceData": False,
            "realInputs": venue_data["realInputs"],
        }
    )
    generated = asyncio.run(
        experience_studio.build_experience_studio_payload(
            {
                **plan["recommendedPlan"]["payload"],
                "useLlm": False,
                "useCreativeReasoning": False,
            },
            None,
        )
    )
    package = generated["draft"]["creativePackage"]

    assert plan["parsedBrief"]["templateId"] == "date-night"
    assert generated["draft"]["title"] == "Date Night Route"
    assert package["executiveConcept"]["name"] == "Evening Ease Route"
    assert "relaxed evening route" in package["executiveConcept"]["oneLine"]
    assert "private access" in package["executiveConcept"]["guestPromise"]
    assert package["venuePattern"]["id"] == "date_night"
    assert package["venuePattern"]["recommendedArc"]
    assert package["contentCreationModel"]["mode"] == "evidence_backed_package_content_v1"
    assert package["contentCreationModel"]["email"]["subject"] == "A relaxed date-night route"
    assert [item["headline"] for item in package["signageSet"][:3]] == ["Evening route", "Food or view", "Photo close"]
    assert "Open softly" in generated["draft"]["route"][0]["purpose"]
    assert "start the evening route" in generated["draft"]["route"][0]["guestCopy"]
    assert len(generated["draft"]["route"]) >= 4
    assert package["channelMatrix"]


def test_visual_asset_studio_adds_vertex_poster_prompts(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    generated = asyncio.run(
        experience_studio.build_experience_studio_payload(
            {
                "templateId": "festival-plan",
                "audience": "families and friend groups",
                "tone": "festive, respectful, warm",
                "constraints": "Use verified venue facts only.",
                "useVenueExperienceData": False,
                "realInputs": venue_data["realInputs"],
                "useLlm": False,
            },
            None,
        )
    )
    package = generated["draft"]["creativePackage"]
    visual = package["visualAssetStudio"]

    assert visual["mode"] == "vertex_imagen_visual_asset_studio_v1"
    assert visual["model"] == "imagen-4.0-generate-001"
    assert visual["status"] in {"prompt_ready_provider_not_configured", "configured_ready"}
    assert {prompt["id"] for prompt in visual["prompts"]} >= {"poster_hero", "app_tile", "signage_mockup", "social_story"}
    assert "Marketing poster key art" in visual["prompts"][0]["prompt"]
    assert visual["posterCreation"]["publishAuthority"] is False

    assets = experience_studio.generate_experience_studio_visual_assets({"draft": generated["draft"], "generateImages": False, "promptIds": ["poster_hero"]})
    assert assets["status"] == "prompt_ready"
    assert assets["selectedPrompts"][0]["id"] == "poster_hero"
    assert assets["providerReadiness"]["ready"] in {False, True}


def test_visual_asset_persistence_writes_images_and_receipt(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    output_dir = tmp_path / "visuals"
    monkeypatch.setenv("PARKPULSE_EXPERIENCE_STUDIO_VISUAL_OUTPUT_DIR", str(output_dir))

    persistence = experience_studio._persist_visual_asset_images(
        [
            {
                "status": "generated",
                "model": "imagen-4.0-generate-001",
                "promptId": "poster_hero",
                "images": [{"id": "poster_hero_1", "mimeType": "image/png", "dataUrl": "data:image/png;base64,aGVsbG8="}],
            }
        ],
        {"executiveConcept": {"name": "Festival Passport Path"}},
        [{"id": "poster_hero", "label": "Campaign poster hero", "format": "poster"}],
    )

    assert persistence["status"] == "saved"
    assert persistence["assetCount"] == 1
    assert output_dir.joinpath("festival-passport-path-poster-hero-1.png").exists()
    assert output_dir.joinpath("festival-passport-path-visual-assets.json").exists()
    assert persistence["assets"][0]["reviewStatus"] == "review_draft"


def test_event_team_pdf_builds_from_current_package(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    output_dir = tmp_path / "pdfs"
    monkeypatch.setenv("PARKPULSE_EXPERIENCE_STUDIO_VISUAL_OUTPUT_DIR", str(output_dir))
    generated = asyncio.run(
        experience_studio.build_experience_studio_payload(
            {
                "templateId": "festival-plan",
                "audience": "families, friend groups, and multigenerational guests",
                "tone": "festive, respectful, warm, culturally careful",
                "seasonalTheme": "Chinese New Year festival month",
                "useVenueExperienceData": True,
            },
            None,
        )
    )

    result = experience_studio.generate_experience_studio_event_team_pdf({"draft": generated["draft"], "creativePackage": generated["draft"]["creativePackage"]})

    assert result["status"] == "generated"
    assert result["mode"] == "experience_studio_event_team_pdf"
    assert result["pdfPath"].endswith(".pdf")
    assert result["pdfDataUrl"].startswith("data:application/pdf;base64,")
    assert output_dir.joinpath(result["fileName"]).exists()
    assert result["sizeBytes"] > 1000
    assert "review draft" in result["boundary"].lower()


def test_approved_finished_package_becomes_memory_without_seed_examples(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a chinese new year festival plan that run for a month",
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "festive, respectful, clear",
            "useVenueExperienceData": False,
            "realInputs": venue_data["realInputs"],
        }
    )
    generated = asyncio.run(
        experience_studio.build_experience_studio_payload(
            {
                **plan["recommendedPlan"]["payload"],
                "useLlm": False,
                "useCreativeReasoning": False,
            },
            None,
        )
    )
    saved = experience_studio.save_experience_studio_draft(
        {
            "templateId": "rainy-day",
            "draft": generated["draft"],
            "actor": "experience_designer",
        }
    )
    draft_id = saved["draftRecord"]["id"]

    assert saved["draftRecord"]["templateId"] == "festival-plan"

    approved = experience_studio.update_experience_studio_draft_status(
        draft_id,
        {
            "status": "approved",
            "actor": "creative_lead",
            "note": "Approved for bounded Experience Studio memory retrieval in demo.",
        },
    )

    assert approved["status"] == "updated"
    assert approved["memoryPersistence"]["finishedWork"]["collection"] == "experience_studio_approved_work"

    followup = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create another chinese new year festival plan for families",
            "templateId": "festival-plan",
            "audience": "mixed family groups",
            "tone": "festive, respectful, clear",
            "useVenueExperienceData": False,
            "realInputs": venue_data["realInputs"],
        }
    )

    memory_gate = followup["retrievalEvidence"]["memoryGate"]
    assert memory_gate["status"] == "accepted"
    assert memory_gate["accepted"][0]["id"] == draft_id
    assert followup["retrievalEvidence"]["evidenceSummary"]["memoryCount"] == 1
    memory_tool = next(tool for tool in followup["planningTools"] if tool["id"] == "retrieval_evidence")
    assert memory_tool["data"]["memoryGate"]["accepted"][0]["id"] == draft_id


def test_semantic_studio_memory_retrieves_synthetic_context_without_exposing_vectors(monkeypatch, tmp_path):
    experience_studio, mongo_memory = _fresh_modules(monkeypatch, tmp_path)

    injected = experience_studio.inject_experience_studio_synthetic_memory({"actor": "pytest", "templateId": "festival-plan"})
    assert injected["status"] == "injected"
    assert injected["writeCount"] == 32

    retrieved = mongo_memory.retrieve_experience_studio_memory(
        "Create a Chinese New Year festival plan that runs for a month with food, craft, signage, email, and staff cues.",
        [
            "experience_studio_approved_work",
            "experience_studio_learning_rules",
            "experience_studio_eval_examples",
        ],
        template_id="festival-plan",
        limit=8,
    )

    assert retrieved["status"] == "ready"
    assert retrieved["retrieval"]["returnedCount"] >= 3
    assert retrieved["retrieval"]["rerank"]["status"] in {"not_configured", "fallback", "ready"}
    assert any(row.get("templateId") == "festival-plan" for row in retrieved["rows"])
    assert any((row.get("_retrieval") or {}).get("collection") == "experience_studio_approved_work" for row in retrieved["rows"])
    assert any((row.get("_retrieval") or {}).get("collection") == "experience_studio_learning_rules" for row in retrieved["rows"])
    assert all("embedding" not in row and "modelEmbedding" not in row and "embeddingText" not in row for row in retrieved["rows"])

    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a Chinese New Year festival plan that runs for a month.",
            "templateId": "rainy-day",
            "audience": "families",
            "tone": "festive and respectful",
            "useVenueExperienceData": False,
            "realInputs": {"source": "test", "locations": ["Front Gate", "Dragon Arch Photo Spot", "Lagoon Lanterns", "Harbor Treats", "Theater B"]},
        }
    )

    assert plan["parsedBrief"]["templateId"] == "festival-plan"
    assert plan["retrievalEvidence"]["memoryGate"]["status"] == "accepted"
    assert plan["retrievalEvidence"]["evidenceSummary"]["learningRuleCount"] >= 1
    assert plan["recommendedPlan"]["label"] == "Lantern Wishes festival concept"
    assert plan["retrievalEvidence"]["memoryGate"]["accepted"][0]["selectedConceptName"]


def test_llm_planner_uses_tool_list_and_carries_reasoning_to_package(monkeypatch, tmp_path):
    experience_studio, _ = _fresh_modules(monkeypatch, tmp_path)
    from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export

    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    seen_prompt = {}

    def fake_planner(prompt, *, timeout_seconds, max_output_tokens, temperature):
        seen_prompt.update(prompt)
        tool_ids = [tool["id"] for tool in prompt["planning_tools"]]
        assert "template_catalog" in tool_ids
        assert "venue_profile" in tool_ids
        assert "route_pattern" in tool_ids
        assert "retrieval_evidence" in tool_ids
        assert "agent_workflow" in tool_ids
        retrieval_tool = next(tool for tool in prompt["planning_tools"] if tool["id"] == "retrieval_evidence")
        assert retrieval_tool["data"]["retrievedEvidence"]
        assert retrieval_tool["data"]["memoryGate"]["authority"] == "approved_or_ready_finished_work_only"
        assert prompt["designer_request"].startswith("Create a chinese new year")
        return {
            "transport": "fake_llm",
            "finish_reason": "STOP",
            "usage_metadata": {"totalTokenCount": 123},
            "generated": {
                "planName": "Lantern Wishes Month",
                "selectedTemplateId": "festival-plan",
                "selectedToolIds": ["template_catalog", "venue_profile", "route_pattern", "channels_and_voice"],
                "strategy": {
                    "objective": "Create a month-long Chinese New Year festival with repeatable weekly discovery and a reviewable finale.",
                    "audienceReasoning": "Families need clear optional paths, short participation beats, and culture-safe copy review.",
                    "routeStrategy": "Start at the verified entry, build through food/craft/show beats, and close with a lantern/photo moment.",
                    "channelStrategy": "Guest app carries the month map; signage marks optional stops; email frames weekly returns; staff cue keeps claims reviewable.",
                    "riskTradeoffs": ["Do not promise a prize, cultural performance, or access unless the owner approves it."],
                },
                "programPhases": [
                    {"name": "Opening weekend", "duration": "Days 1-3", "guestJob": "pick a first wish/passport path", "heroMoment": "entry lantern/photo cue", "channels": ["guest_app", "signage"], "reviewGate": "brand and cultural review"},
                    {"name": "Discovery weeks", "duration": "Weeks 1-3", "guestJob": "return for rotating food, craft, and show prompts", "heroMoment": "weekly verified stop prompt", "channels": ["email", "guest_app"], "reviewGate": "program calendar review"},
                    {"name": "Finale week", "duration": "Final week", "guestJob": "close the month without a prize promise", "heroMoment": "lantern finale placeholder", "channels": ["staff_cue"], "reviewGate": "operations and accessibility review"},
                ],
                "signatureMoments": [
                    {"name": "Wish Wall Start", "venueEvidence": "Front Gate", "guestAction": "choose an optional wish prompt", "reviewNeed": "signage placement approval"}
                ],
                "evidenceUse": [
                    {"evidenceId": "location:Front Gate", "usedFor": "entry orientation and first optional photo cue"}
                ],
                "agentStageNotes": [
                    {"stageId": "retrieval_agent", "decision": "use verified route evidence and keep cultural programming owner-reviewed"}
                ],
                "contentPillars": ["return visits", "optional participation", "culture-safe review"],
                "recommendedPayloadPatch": {
                    "creativeDirection": "month-long lantern festival programming",
                    "storyArc": "Opening wish -> weekly discovery -> food and craft beats -> show spotlight -> lantern finale",
                    "sensoryLevel": "balanced",
                    "walkingPace": "flexible",
                    "outputPackage": "complete month festival package",
                    "seasonalTheme": "Chinese New Year festival month",
                    "constraints": "Use reviewable cultural references and verified venue stops only.",
                },
                "ownerQuestions": ["Which cultural references and participation mechanics are approved?"],
                "reviewBoundaries": ["No prize, live performance, or availability promises."],
            },
        }

    monkeypatch.setattr(experience_studio, "_run_experience_studio_llm_json_sync", fake_planner)

    plan = experience_studio.build_experience_studio_conversation_plan(
        {
            "message": "Create a chinese new year festival plan that run for a month",
            "templateId": "rainy-day",
            "audience": "mixed family groups",
            "tone": "festive, respectful, clear",
            "useVenueExperienceData": False,
            "realInputs": venue_data["realInputs"],
            "useLlmPlanner": True,
        }
    )

    assert plan["parsedBrief"]["templateId"] == "festival-plan"
    assert plan["llmReasoning"]["status"] == "ready"
    assert plan["llmReasoning"]["transport"] == "fake_llm"
    assert plan["llmReasoning"]["acceptedPayloadFields"]
    assert plan["reasonedPlan"]["status"] == "llm_reasoned"
    assert plan["reasonedPlan"]["programPhases"][0]["name"] == "Opening weekend"
    assert plan["retrievalEvidence"]["status"] == "ready"
    assert plan["retrievalEvidence"]["retrievedEvidence"]
    assert plan["retrievalEvidence"]["memoryGate"]["authority"] == "approved_or_ready_finished_work_only"
    assert len(plan["agentWorkflow"]["stages"]) >= 5
    assert plan["productReadiness"]["score"] >= 70
    assert plan["reasonedPlan"]["evidenceUse"][0]["evidenceId"] == "location:Front Gate"
    assert plan["reasonedPlan"]["agentStageNotes"][0]["stageId"] == "retrieval_agent"
    assert plan["recommendedPlan"]["label"] == "Lantern Wishes Month"
    assert plan["recommendedPlan"]["payload"]["creativeDirection"] == "month-long lantern festival programming"
    assert plan["recommendedPlan"]["payload"]["plannerContext"]["llmReasoning"]["status"] == "ready"
    assert plan["recommendedPlan"]["payload"]["plannerContext"]["retrievalEvidence"]["retrievedEvidence"]
    assert plan["recommendedPlan"]["payload"]["plannerContext"]["agentWorkflow"]["stages"]
    assert plan["recommendedPlan"]["payload"]["plannerContext"]["productReadiness"]["score"] >= 70
    assert {tool["id"] for tool in plan["planningTools"]} >= {"template_catalog", "venue_profile", "route_pattern", "channels_and_voice", "retrieval_evidence", "agent_workflow"}

    generated = asyncio.run(
        experience_studio.build_experience_studio_payload(
            {
                **plan["recommendedPlan"]["payload"],
                "useLlm": False,
                "useCreativeReasoning": False,
            },
            None,
        )
    )
    reasoned_package = generated["draft"]["creativePackage"]["plannerReasonedPlan"]
    assert reasoned_package["status"] == "llm_reasoned"
    assert reasoned_package["programPhases"][1]["name"] == "Discovery weeks"
    assert reasoned_package["strategy"]["objective"].startswith("Create a month-long Chinese New Year")
    assert reasoned_package["retrievalEvidence"]["retrievedEvidence"]
    assert reasoned_package["agentWorkflow"]["stages"][0]["id"] == "brief_interpreter"
    assert reasoned_package["productReadiness"]["score"] >= 70
    assert generated["draft"]["creativePackage"]["productionDetail"]["plannerEvidence"]["llmReasoningStatus"] == "ready"
    assert generated["draft"]["creativePackage"]["productionDetail"]["plannerEvidence"]["retrievalSummary"]["locationCount"] >= 1
    assert generated["draft"]["creativePackage"]["productReadiness"]["score"] >= 70
    assert "rainy" not in json.dumps(generated["draft"]["creativePackage"], default=str).lower()


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
