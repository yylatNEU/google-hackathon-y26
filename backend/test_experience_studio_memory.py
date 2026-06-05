import asyncio
import importlib


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
