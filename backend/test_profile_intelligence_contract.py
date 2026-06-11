import copy

from venue_experience_data import approved_synthetic_venue_export, build_venue_experience_data_from_export, profile_intelligence_contract, validate_venue_experience_export, venue_profile_gap_contract


def _certified_profile_intelligence():
    return {
        "version": "profile_intelligence_v1",
        "certified_paths": [
            {
                "id": "path_indoor_launch_to_theater_b",
                "fromZoneId": "indoorHub",
                "toZoneId": "indoorHub",
                "estimatedWalkMinutes": 4,
                "stepFree": True,
                "covered": True,
                "certificationStatus": "venue_certified",
                "source": "venue_facilities_path_audit",
            }
        ],
        "capacity_model": {
            "status": "venue_certified",
            "zoneComfort": [
                {
                    "zoneId": "indoorHub",
                    "comfortCapacityEstimate": 420,
                    "seatingCapacity": 140,
                    "decompressionCapacity": 48,
                    "source": "venue_capacity_sheet",
                }
            ],
        },
        "timing_model": {
            "status": "venue_scheduled",
            "showtimes": [{"id": "theater_b_1400", "name": "Theater B Cooling Show", "startsAtLocal": "14:00", "endsAtLocal": "14:18"}],
            "blackoutWindows": [{"id": "parade_setup", "startsAtLocal": "15:30", "endsAtLocal": "16:00", "affectedZoneIds": ["coasterPlaza"]}],
        },
        "review_owners": {"experience_design": "Park Experience Content Owner", "accessibility": "Accessibility Review Lead"},
    }


def _without_synthetic_source_names(value):
    if isinstance(value, dict):
        return {str(key).replace("synthetic_", "venue_"): _without_synthetic_source_names(row) for key, row in value.items()}
    if isinstance(value, list):
        return [_without_synthetic_source_names(row) for row in value]
    if isinstance(value, str):
        return value.replace("synthetic_", "venue_").replace("synthetic.", "venue.")
    return value


def test_profile_intelligence_contract_declares_real_venue_requirements():
    contract = profile_intelligence_contract()

    assert contract["version"] == "profile_intelligence_v1"
    assert contract["components"]["certifiedPaths"]["requiredForRealVenueReady"] is True
    assert contract["components"]["capacityModel"]["certifiedValue"]["status"] == "venue_certified"
    assert contract["components"]["timingModel"]["certifiedValue"]["status"] == "venue_scheduled"


def test_certified_profile_intelligence_clears_derived_quality_gaps():
    export = copy.deepcopy(approved_synthetic_venue_export())
    export["profile_intelligence"] = _certified_profile_intelligence()

    venue_data = build_venue_experience_data_from_export(export, loaded_from="certified_profile_test.json")
    intelligence = venue_data["realInputs"]["profileIntelligence"]

    assert intelligence["source"] == "venue_profile.profile_intelligence"
    assert intelligence["readiness"]["status"] == "certified"
    assert intelligence["readiness"]["realVenueReady"] is True
    assert intelligence["qualityGaps"] == []
    assert venue_data["sourceIntegrity"]["realVenueReady"] is False
    assert venue_data["sourceIntegrity"]["usesApprovedSyntheticProfile"] is True


def test_approved_synthetic_profile_supplies_creative_venue_intelligence():
    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    real_inputs = venue_data["realInputs"]
    intelligence = real_inputs["profileIntelligence"]

    assert len(real_inputs["guestSegments"]) >= 6
    assert intelligence["readiness"]["status"] == "certified"
    assert len(intelligence["experienceRules"]["routePatterns"]) == 19
    assert intelligence["experienceRules"]["routePatterns"]["rainy_day"]["mustInclude"]
    assert intelligence["experienceRules"]["routePatterns"]["date_night"]["recommendedArc"]
    assert intelligence["experienceRules"]["routePatterns"]["food_festival"]["avoidClaims"]
    assert intelligence["experienceRules"]["routePatterns"]["safety_signage"]["mustInclude"]
    assert "Dragon Arch Photo Spot" in intelligence["experienceRules"]["halloweenCandidateLocations"]
    assert intelligence["brandBible"]["thematicLexicon"]["dragon"]
    assert "priority access" in intelligence["brandBible"]["bannedClaims"]
    assert intelligence["modulePolicy"]["experience_studio"]["preferredOutputs"]
    assert intelligence["learningSchema"]["feedbackLabels"]
    assert intelligence["liveFeedBindings"]["weather"]
    assert real_inputs["currentStatus"]["attractions"]
    assert real_inputs["pathStatus"]["routeSegments"]
    assert real_inputs["signageInventory"]["placements"]
    assert real_inputs["channelTemplates"]["templates"]["guest_app"]["requiredClauses"]
    assert real_inputs["operatingCalendar"]["eventWindows"]
    assert real_inputs["weatherPolicy"]["rain"]["blockedClaims"]
    assert intelligence["operatingContext"]["coverage"]["signagePlacements"] >= 4
    assert intelligence["coverage"]["currentOptions"] >= 5
    assert intelligence["coverage"]["channelTemplates"] >= 4
    assert intelligence["coverage"]["venueOwnedOverrides"] >= 8


def test_venue_profile_gap_contract_consolidates_synthetic_operating_coverage():
    venue_data = build_venue_experience_data_from_export(approved_synthetic_venue_export(), loaded_from="approved_profile.json")
    real_inputs = venue_data["realInputs"]
    intelligence = real_inputs["profileIntelligence"]
    contract = venue_profile_gap_contract(
        real_inputs,
        real_inputs["venueIdentity"]["profileType"],
        intelligence["readiness"],
        intelligence["coverage"],
        [],
        include_generation_requirements=True,
    )

    assert contract["status"] == "synthetic_complete_review_required"
    assert contract["productionRealVenueReady"] is False
    assert contract["missingForProduction"] == ["real venue source feed instead of approved synthetic profile"]
    assert "synthetic channel-owner CRM/app/signage/staff templates" in contract["filledForSyntheticDemo"]
    assert contract["syntheticOperatingCoverage"]["currentOptions"] >= 5
    assert contract["syntheticOperatingCoverage"]["approvalWorkflowRows"] >= 4


def test_real_venue_ready_requires_certified_profile_intelligence_and_non_synthetic_sources():
    export = _without_synthetic_source_names(copy.deepcopy(approved_synthetic_venue_export()))
    export["venue_identity"]["profile_type"] = "real_venue"
    export["source_catalog"]["profile_type"] = "real_venue"
    export["profile_intelligence"] = _certified_profile_intelligence()

    validation = validate_venue_experience_export(export)
    venue_data = build_venue_experience_data_from_export(export, loaded_from="real_venue_certified_profile.json")

    assert validation["status"] == "studio_ready"
    assert validation["profileIntelligence"]["status"] == "certified"
    assert validation["realVenueReady"] is True
    assert venue_data["sourceIntegrity"]["usesApprovedSyntheticProfile"] is False
    assert venue_data["sourceIntegrity"]["realVenueReady"] is True
