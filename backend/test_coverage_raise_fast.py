from __future__ import annotations

import asyncio
import json
import os
import sys
import types

import main
import pytest
from park_simulation import ParkSimulation


def run(coro):
    return asyncio.run(coro)


def ready_accessibility_venue_profile():
    return {
        "venueIdentity": {
            "venueId": "unit-park",
            "name": "Unit Test Park",
            "publicZones": [{"id": "quietHarbor", "name": "Quiet Harbor"}, {"id": "coveredPlaza", "name": "Covered Plaza"}],
        },
        "readiness": {
            "status": "ready",
            "autofillAllowed": True,
            "loadedFrom": "unit-profile",
            "counts": {"safetyInstructions": 2},
            "issues": [],
        },
        "sourceIntegrity": {"status": "synthetic_test"},
        "realInputs": {
            "source": "unit_test_profile",
            "safetyInstructions": ["Confirm ride transfer assistance with staff.", "Confirm allergy ingredients with trained staff."],
            "locationDetails": {
                "restroom": {
                    "kind": "restrooms",
                    "zoneId": "quietHarbor",
                    "name": "Quiet Harbor Restrooms",
                    "accessible": True,
                },
                "quiet": {
                    "kind": "quiet_or_cooling",
                    "zoneId": "quietHarbor",
                    "name": "Quiet Harbor",
                    "indoor": True,
                    "covered": True,
                    "bestFor": ["low sensory", "shade"],
                    "services": ["Guest Services"],
                    "accessibilityNote": "Step-free indoor rest area.",
                    "sensoryNote": "Calm low-noise room.",
                },
                "dining": {
                    "kind": "food",
                    "zoneId": "coveredPlaza",
                    "name": "Harbor Cafe",
                    "indoor": True,
                    "covered": True,
                    "dietaryTags": ["peanut option", "tree nut option", "gluten option"],
                    "seating": "covered side patio",
                    "mobileOrder": True,
                    "cuisine": "Mediterranean",
                    "accessibilityNote": "Step-free counter.",
                    "sensoryNote": "Quieter lunch service before noon.",
                },
                "show": {
                    "kind": "show",
                    "zoneId": "coveredPlaza",
                    "name": "Story Garden",
                    "indoor": True,
                    "covered": True,
                    "durationMinutes": 25,
                    "familyFit": "all ages",
                    "accessibilityNote": "Step-free seating row.",
                    "sensoryNote": "Gentle narration without flashing lights.",
                },
                "coaster": {
                    "kind": "attraction",
                    "zoneId": "coasterPlaza",
                    "name": "Launch Coaster",
                    "thrillLevel": "high launch",
                    "category": "thrill",
                    "accessibilityNote": "Transfer required.",
                    "sensoryNote": "Loud launch and flashing lights.",
                },
            },
            "zoneDetails": {
                "quietHarbor": {"role": "reset", "quietOrCooling": True, "indoorOrSheltered": True},
                "coveredPlaza": {"role": "family_services", "quietOrCooling": True, "indoorOrSheltered": True},
                "coasterPlaza": {"role": "attraction_demand", "quietOrCooling": False, "indoorOrSheltered": False},
            },
            "profileIntelligence": {
                "source": "unit_intelligence",
                "coverage": {"certifiedPaths": 1, "capacityZones": 2},
                "qualityGaps": ["manual validation needed for west path"],
                "capacityModel": {
                    "zoneComfort": [
                        {"zoneId": "quietHarbor", "spillbackRisk": "low", "comfortCapacityEstimate": 180},
                        {"zoneId": "coveredPlaza", "spillbackRisk": "high", "comfortCapacityEstimate": 120},
                    ]
                },
                "certifiedPaths": [
                    {
                        "fromZoneId": "quietHarbor",
                        "toZoneId": "coveredPlaza",
                        "estimatedWalkMinutes": 6,
                        "certificationStatus": "derived",
                        "allowedUses": ["planning"],
                        "blockedClaims": ["Do not claim ADA certification."],
                    }
                ],
                "segmentNeeds": {
                    "allergy_or_dietary_guests": {
                        "preferredPace": "slow",
                        "preferredZones": ["quietHarbor", "coveredPlaza"],
                        "avoid": ["dense queues", "long exposed walks"],
                        "requiredHandoff": ["dining_manager"],
                    },
                    "low_sensory_guests": {
                        "preferredPace": "slow",
                        "preferredZones": ["quietHarbor"],
                        "avoid": ["dense queues"],
                        "requiredHandoff": ["guest_services"],
                    },
                },
                "modulePolicy": {
                    "accessibility_journey": {
                        "mayRecommend": ["public route planning"],
                        "mustReview": ["allergy", "medical", "route availability"],
                        "neverClaim": ["ADA certification", "allergen-free food"],
                    }
                },
                "learningSchema": {
                    "version": "unit_schema_v2",
                    "feedbackLabels": [
                        "guest_completed_route",
                        "allergy_staff_confirmed",
                        "blocked_internal_note",
                        "private_debug_label",
                    ],
                },
            },
        },
    }


def ready_accessibility_park_state():
    return {
        "guestFlow": {
            "zones": [
                {"id": "quietHarbor", "density": 12, "waitMins": 2, "comfortScore": 93},
                {"id": "coveredPlaza", "density": 26, "waitMins": 4, "comfortScore": 86},
                {"id": "coasterPlaza", "density": 88, "waitMins": 45, "comfortScore": 42},
            ],
            "rides": [
                {"id": "story_garden_live", "name": "Story Garden", "zone": "coveredPlaza", "zoneName": "Covered Plaza", "status": "open", "waitMins": 9},
                {"id": "launch_live", "name": "Launch Coaster", "zone": "coasterPlaza", "zoneName": "Coaster Plaza", "status": "open", "waitMins": 32},
                {"id": "closed_live", "name": "Closed Tower", "zone": "coasterPlaza", "status": "down", "waitMins": 0},
            ],
        },
        "foodInventory": {
            "locations": [
                {
                    "id": "harborCafe",
                    "pickupEtaMinutes": 7,
                    "mobileOrderBacklog": 8,
                    "availableItems": ["rice bowl", "fruit cup"],
                }
            ]
        },
        "weather": {"heatIndexF": 96, "stormRisk": 35},
        "incidentReadiness": {"accessibilityRoutesOpen": False},
    }


def current_venue_profile_fixture():
    return {
        "venueIdentity": {
            "venueId": "old-park",
            "name": "Old Park",
            "profileType": "theme_park",
            "description": "Old profile",
            "primaryAudiences": ["families"],
            "publicZones": [{"id": "z1", "name": "Zone One", "kind": "calm"}, {"id": "z2", "name": "Zone Two"}],
        },
        "realInputs": {
            "locationDetails": {
                "cafe": {"name": "Harbor Cafe", "kind": "food", "zoneId": "z1", "sourceIds": ["ignored"]},
                "ride": {"name": "Old Ride", "kind": "attraction", "zoneId": "z2"},
            },
            "channelOwners": {"ops": "alice"},
            "safetyInstructions": ["Keep left", "Old rule"],
        },
        "readiness": {"counts": {"locationDetails": 2, "safetyInstructions": 2}},
        "sourceIntegrity": {"status": "current"},
    }


def candidate_venue_profile_fixture():
    return {
        "venueIdentity": {
            "venueId": "new-park",
            "name": "New Park",
            "profileType": "theme_park",
            "description": "New profile",
            "primaryAudiences": ["families", "teens"],
            "publicZones": [{"id": "z1", "name": "Zone One", "kind": "active"}, {"id": "z3", "name": "Zone Three"}],
        },
        "realInputs": {
            "locationDetails": {
                "cafe": {"name": "Harbor Cafe", "kind": "food", "zoneId": "z3"},
                "new": {"name": "New Stage", "kind": "show", "zoneId": "z3"},
            },
            "channelOwners": {"ops": "bob", "food": "casey"},
            "safetyInstructions": ["Keep left", "New rule"],
        },
        "readiness": {"counts": {"locationDetails": 2, "safetyInstructions": 2, "publicZones": 2}},
        "sourceIntegrity": {"status": "candidate"},
    }


def test_accessibility_scope_and_blocked_journey(monkeypatch):
    import accessibility_journey

    blocked_profile = {
        "venueIdentity": {"venueId": "blocked", "name": "Blocked Park"},
        "readiness": {
            "status": "not_ready",
            "autofillAllowed": False,
            "counts": {"locationDetails": 0},
            "issues": ["missing locationDetails"],
            "loadedFrom": "unit",
        },
        "sourceIntegrity": {"status": "missing"},
        "realInputs": {"source": "unit_blocked"},
    }
    monkeypatch.setattr(accessibility_journey, "build_venue_profile", lambda: blocked_profile)

    scope = accessibility_journey.build_accessibility_scope()
    assert scope["venueProfile"]["status"] == "not_ready"
    assert scope["venueProfile"]["issues"] == ["missing locationDetails"]
    assert "allergy ingredient confirmation" in scope["human_authority"]

    result = accessibility_journey.build_accessibility_journey(
        {
            "request": "Need wheelchair route for peanut allergy and first aid check",
            "durationMinutes": "30",
            "currentLocation": "",
            "allergies": "peanut/tree nut",
            "nearRestrooms": True,
        },
        {"guestFlow": {"zones": []}},
    )
    assert result["status"] == "blocked"
    assert result["summary"]["durationMinutes"] == 45
    assert result["summary"]["requiresHumanReview"] is True
    assert result["profile"]["guestSegmentId"] == "allergy_or_dietary_guests"
    assert result["profile"]["avoidStairs"] is True
    assert result["staffHandoff"]["owner"] == "Venue Profile owner"
    assert result["evidence"][0]["id"] == "venue_profile_blocked"


def test_accessibility_journey_ready_profile_filters_and_receipts(monkeypatch):
    import accessibility_journey

    monkeypatch.setattr(accessibility_journey, "build_venue_profile", ready_accessibility_venue_profile)
    result = accessibility_journey.build_accessibility_journey(
        {
            "prompt": "Low sensory indoor wheelchair route with minimal walking for peanut allergy",
            "party": "family with elderly guest and stroller",
            "notes": "avoid loud shows, need restroom and shade breaks",
            "needs": ["mobility", "language"],
            "allergies": ["peanut"],
            "duration_minutes": 165,
            "current_location": "Entrance Plaza",
            "indoorBreaks": True,
            "minimalWalking": True,
            "nearRestrooms": True,
        },
        ready_accessibility_park_state(),
    )

    assert result["status"] == "ok"
    assert result["summary"]["durationMinutes"] == 165
    assert result["summary"]["requiresHumanReview"] is True
    assert result["summary"]["reviewReason"] == "Accessibility route status needs staff confirmation."
    assert result["staffHandoff"]["owner"] == "Dining manager or allergy-trained staff"
    assert result["diningOptions"][0]["id"] == "harborCafe"
    assert result["diningOptions"][0]["staffConfirmationRequired"] is True
    assert result["attractionOptions"][0]["name"] in {"Story Garden", "Quiet Harbor reset activity"}
    assert all(option["name"] != "Launch Coaster" for option in result["attractionOptions"])
    assert len(result["planSteps"]) >= 4
    assert any("Do not claim ADA certification." in risk for step in result["planSteps"] for risk in step["risks"])
    assert result["breakPlan"]["cadenceMinutes"] == 35
    assert "Allergy result is a dining shortlist, not an allergen-free guarantee." in result["guardrails"]
    assert "Live accessibility route status is degraded; confirm route with staff before moving." in result["guardrails"]
    assert result["profileIntelligence"]["source"] == "unit_intelligence"
    assert result["profileIntelligence"]["modulePolicy"]["neverClaim"] == ["ADA certification", "allergen-free food"]
    assert result["learningReceipt"]["schemaVersion"] == "unit_schema_v2"
    assert result["learningReceipt"]["eligibleFeedbackLabels"] == [
        "guest_completed_route",
        "allergy_staff_confirmed",
        "blocked_internal_note",
    ]
    assert result["runtime"]["liveParkState"] is True


def test_accessibility_helper_edges():
    import accessibility_journey

    assert accessibility_journey._location_id("  123 Main Plaza! ") == "123MainPlaza"
    assert accessibility_journey._location_id(" !!! ") == "venueLocation"
    assert accessibility_journey._safe_int("bad", 9) == 9
    assert accessibility_journey._safe_int("12.8", 9) == 12
    assert accessibility_journey._guest_segment_id({"low_sensory"}, [], "") == "low_sensory_guests"
    assert accessibility_journey._guest_segment_id(set(), [], "rain storm") == "rainy_day_parties"
    assert accessibility_journey._guest_segment_id(set(), [], "thrill coaster") == "thrill_seekers"
    assert accessibility_journey._guest_segment_id(set(), [], "") == "families_with_strollers"
    assert accessibility_journey._allergens_from_payload({}, "dairy soy") == ["dairy", "soy"]
    assert accessibility_journey._sensory_load({"sensoryNote": "loud flashing drop", "indoor": True}) == "high"
    assert accessibility_journey._sensory_load({"covered": True}) == "medium"
    assert accessibility_journey._sensory_load({}) == "medium"

    profile = accessibility_journey._profile_from_payload({"request": "just a relaxed visit", "durationMinutes": 999})
    assert profile["needs"] == ["family_care"]
    assert profile["durationMinutes"] == 360

    catalog = accessibility_journey._venue_accessibility_catalog(ready_accessibility_venue_profile())
    assert accessibility_journey._path_by_zone_pair({"certifiedPaths": ["bad-row", {"fromZoneId": "", "toZoneId": "x"}]}) == {}
    assert accessibility_journey._walk_minutes("quietHarbor", "coveredPlaza", catalog, 99) == 6
    assert accessibility_journey._walk_minutes("quietHarbor", "unknown", catalog, 99) == 20
    assert "Path record is derived, not venue-certified." in accessibility_journey._route_claim_warnings("quietHarbor", "coveredPlaza", catalog)
    assert "planning estimate" in accessibility_journey._route_claim_warnings("quietHarbor", "missing", catalog)[0]
    assert accessibility_journey._route_claim_warnings("quietHarbor", "quietHarbor", catalog) == []

    first_aid = accessibility_journey._normalize_profile_location(
        {"kind": "first_aid", "zoneId": "aid", "name": "First Aid", "indoor": True},
        {},
    )
    assert first_aid["quietScore"] > 80

    direct_profile = {
        "request": "medical mobility",
        "needs": ["medical", "mobility"],
        "guestSegmentId": "medical",
        "allergies": [],
        "durationMinutes": 90,
        "avoidStairs": True,
        "needsIndoorBreaks": False,
        "nearRestrooms": False,
        "avoidLoudShows": False,
        "minimalWalking": False,
    }
    direct_catalog = {
        "locations": [
            {
                "zoneId": "showZone",
                "id": "showZone",
                "name": "Show Zone",
                "quietScore": 65,
                "indoor": False,
                "stepFree": False,
                "strollerFriendly": False,
                "restrooms": [],
                "breakFeatures": [],
                "sensoryNotes": [],
            }
        ],
        "capacityByZone": {},
        "zoneDetails": {},
        "segmentNeeds": {},
        "qualityGaps": [],
    }
    scored = accessibility_journey._score_zones(direct_profile, [], {}, {"accessibilityRoutesOpen": True}, direct_catalog)
    assert "not step-free" in scored[0]["reasons"]

    dining_catalog = {
        "dining": [{"id": "unsafeCafe", "name": "Unsafe Cafe", "zoneId": "z", "dietaryTags": ["gluten option"], "seating": "", "restrooms": []}]
    }
    assert accessibility_journey._dining_options({"allergies": ["peanut"]}, {"locations": []}, [], dining_catalog) == []

    attraction_profile = {"needs": ["low_sensory"], "avoidLoudShows": False, "avoidStairs": False}
    attraction_catalog = {
        "attractions": [
            {
                "id": "thrill",
                "name": "Thrill Hall",
                "zoneId": "z",
                "sensoryNote": "loud flashing drop",
                "category": "thrill",
                "thrillLevel": "high",
                "stepFree": True,
                "heightRequirementInches": 48,
                "accessibilityNote": "transfer required",
                "indoor": False,
            },
            {
                "id": "closed",
                "name": "Closed Show",
                "zoneId": "z",
                "sensoryNote": "",
                "category": "show",
                "thrillLevel": "",
                "stepFree": True,
                "heightRequirementInches": None,
                "accessibilityNote": "",
                "indoor": True,
            },
            {
                "id": "stairs",
                "name": "Stairs Show",
                "zoneId": "z",
                "sensoryNote": "",
                "category": "show",
                "thrillLevel": "",
                "stepFree": False,
                "heightRequirementInches": None,
                "accessibilityNote": "",
                "indoor": True,
            },
        ]
    }
    options = accessibility_journey._attraction_options(
        attraction_profile,
        [{"name": "Closed Show", "status": "down", "waitMins": 2}, {"name": "Thrill Hall", "status": "open", "waitMins": 5}],
        [{"zoneId": "z", "name": "Zone", "score": 100, "waitMins": 3, "indoor": True, "sensoryNotes": []}],
        attraction_catalog,
    )
    assert any(option["name"] == "Thrill Hall" and option["score"] == 45 for option in options)
    assert all(option["name"] != "Closed Show" for option in options)
    stairs_filtered = accessibility_journey._attraction_options(
        {"needs": [], "avoidLoudShows": False, "avoidStairs": True},
        [{"name": "Stairs Show", "status": "open", "waitMins": 1}],
        [{"zoneId": "z", "name": "Zone", "score": 80}],
        attraction_catalog,
    )
    assert all(option["name"] != "Stairs Show" for option in stairs_filtered)

    assert accessibility_journey._build_steps(profile, [], [], [], catalog) == []
    assert accessibility_journey._guardrails_for_profile({"allergies": [], "needs": ["medical"]}, {})[-1].startswith("Medical constraints")
    assert accessibility_journey._review_reason({"allergies": ["peanut"], "needs": []}, {}) == "Allergy handling must be confirmed by trained dining staff."
    assert accessibility_journey._review_reason({"allergies": [], "needs": ["medical"]}, {}) == "Medical constraints should be reviewed by First Aid or trained staff."
    assert accessibility_journey._review_reason({"allergies": [], "needs": []}, {}) == "Staff review recommended."
    assert accessibility_journey._staff_handoff({"allergies": [], "needs": []}, False)["recommended"] is False
    assert accessibility_journey._staff_handoff({"allergies": [], "needs": ["medical"]}, True)["owner"] == "First Aid"
    assert accessibility_journey._staff_handoff({"allergies": [], "needs": []}, True)["owner"] == "Accessibility Lead"
    assert "low-sensory route" in accessibility_journey._headline({"durationMinutes": 60, "needs": ["low_sensory"]}, [], [])
    assert "mobility-aware route" in accessibility_journey._headline({"durationMinutes": 60, "needs": ["mobility"]}, [], [])
    assert "family route" in accessibility_journey._headline({"durationMinutes": 60, "needs": []}, [], [])
    assert accessibility_journey._confidence({"needs": ["allergy", "medical"], "allergies": ["peanut"]}, [], []) == 35


def test_venue_profile_diff_preview_and_wrappers(monkeypatch):
    import venue_profile

    monkeypatch.setattr(venue_profile, "build_venue_experience_data", current_venue_profile_fixture)
    built = venue_profile.build_venue_profile()
    assert built["mode"] == "venue_profile"
    assert built["globalProfile"]["profileType"] == "theme_park"

    wrapped = venue_profile._with_global_profile(current_venue_profile_fixture())
    assert wrapped["mode"] == "venue_profile"
    assert wrapped["globalProfile"]["venueId"] == "old-park"
    assert "accessibility_journey" in wrapped["globalProfile"]["consumers"]

    diff = venue_profile._profile_diff(current_venue_profile_fixture(), candidate_venue_profile_fixture())
    assert diff["summary"]["replacementRisk"] == "high"
    assert diff["summary"]["totalChanges"] >= 8
    assert diff["locations"]["added"] == ["New Stage"]
    assert diff["locations"]["removed"] == ["Old Ride"]
    assert diff["locations"]["changed"][0]["fields"] == ["zoneId"]
    assert diff["safetyInstructions"] == {"added": ["New rule"], "removed": ["Old rule"]}
    assert {row["channel"] for row in diff["channelOwners"]["changed"]} == {"food", "ops"}
    assert diff["publicZones"]["removed"][0]["id"] == "z2"
    assert diff["identity"]["changed"][0]["field"] == "venueId"
    assert diff["countDelta"]["publicZones"] == 2

    medium_current = current_venue_profile_fixture()
    medium_candidate = current_venue_profile_fixture()
    medium_candidate["realInputs"]["channelOwners"]["ops"] = "bob"
    assert venue_profile._profile_diff(medium_current, medium_candidate)["summary"]["replacementRisk"] == "medium"
    assert venue_profile._profile_diff(current_venue_profile_fixture(), current_venue_profile_fixture())["summary"]["replacementRisk"] == "low"
    assert venue_profile._indexed_by_name({"bad": "skip", "fallback": {"kind": "x"}})["fallback"]["kind"] == "x"
    assert venue_profile._changed_fields({"a": 1, "sourceIds": ["x"]}, {"a": 2, "sourceIds": ["y"]}) == ["a"]
    assert venue_profile._set_diff([" A ", ""], ["a", "B"]) == {"added": ["B"], "removed": []}
    assert venue_profile._zone_key({"name": " Zone "}) == "zone"

    monkeypatch.setattr(venue_profile, "validate_venue_experience_export", lambda export=None: {"wrapped": export})
    assert venue_profile.validate_venue_profile_export({"x": 1}) == {"wrapped": {"x": 1}}

    monkeypatch.setattr(venue_profile, "validate_venue_profile_export", lambda export=None: {"status": "invalid", "issues": ["missing"]})
    blocked = venue_profile.preview_venue_profile_import({})
    assert blocked["status"] == "blocked"
    assert blocked["canActivate"] is False

    monkeypatch.setattr(venue_profile, "validate_venue_profile_export", lambda export=None: {"status": "studio_ready", "checked": export.get("loaded_from")})
    monkeypatch.setattr(venue_profile, "build_venue_profile", current_venue_profile_fixture)
    monkeypatch.setattr(venue_profile, "build_venue_experience_data_from_export", lambda export, loaded_from=None: candidate_venue_profile_fixture())
    preview = venue_profile.preview_venue_profile_import({"source_name": "candidate.json", "export": {"venue": "candidate"}})
    assert preview["status"] == "ready"
    assert preview["sourceName"] == "candidate.json"
    assert preview["validation"]["checked"] == "candidate.json"
    assert preview["canActivate"] is True
    assert preview["candidate"]["venueIdentity"]["venueId"] == "new-park"
    assert preview["current"]["venueIdentity"]["venueId"] == "old-park"

    monkeypatch.setattr(venue_profile, "validate_venue_profile_export", lambda export=None: {"status": "blocked"})
    blocked_preview = venue_profile.preview_venue_profile_import({"export": {"venue": "candidate"}})
    assert blocked_preview["status"] == "blocked"
    assert blocked_preview["message"].startswith("Profile import preview found")

    monkeypatch.setattr(venue_profile, "approved_synthetic_venue_export", lambda: {"approved": True})
    monkeypatch.setattr(venue_profile, "validate_venue_profile_export", lambda export=None: {"status": "studio_ready", "loaded": export.get("loaded_from")})
    approved = venue_profile.approved_synthetic_venue_profile_export()
    assert approved["status"] == "ready"
    assert approved["validation"]["loaded"] == "parkpulse_synthetic_venue_export.approved.json"

    monkeypatch.setattr(venue_profile, "build_venue_profile", lambda: {"venueIdentity": {"venueId": "active"}})
    monkeypatch.setattr(venue_profile, "import_venue_experience_export", lambda payload: {"status": "imported", "venueExperienceData": {"ok": True}})
    imported = venue_profile.import_venue_profile_export({"export": {"ok": True}})
    assert imported["mode"] == "venue_profile_import"
    assert imported["venueProfile"]["venueIdentity"]["venueId"] == "active"
    monkeypatch.setattr(venue_profile, "import_venue_experience_export", lambda payload: {"status": "blocked"})
    imported_without_profile = venue_profile.import_venue_profile_export({})
    assert imported_without_profile["mode"] == "venue_profile_import"
    assert "venueProfile" not in imported_without_profile

    monkeypatch.setattr(venue_profile, "activate_synthetic_venue_export", lambda actor="venue_profile": {"status": "activated", "actor": actor, "venueExperienceData": {"ok": True}})
    activated = venue_profile.activate_synthetic_venue_profile(actor="qa")
    assert activated["mode"] == "venue_profile_synthetic_activation"
    assert activated["actor"] == "qa"
    assert activated["venueProfile"]["venueIdentity"]["venueId"] == "active"


def test_customer_emergency_incident_store_lifecycle_and_redaction(monkeypatch):
    import builtins
    import customer_emergency_incidents as incidents

    incidents.reset_customer_emergency_incidents()
    try:
        redacted = incidents.redact_customer_text("email guest@example.com phone 415-555-1212 badge 123456")
        assert redacted["changed"] is True
        assert "[redacted-email]" in redacted["text"]
        assert "[redacted-phone]" in redacted["text"]
        assert "[redacted-number]" in redacted["text"]

        classification = {
            "severity": "life_safety",
            "escalation_level": "critical",
            "recommended_owner": "Safety Lead",
            "requires_human_review": True,
        }
        created = incidents.create_customer_emergency_incident(
            {
                "idempotencyKey": "incident-1",
                "text": "Guest needs help at gate. contact guest@example.com or 415-555-1212",
                "location": "North Gate",
                "zoneId": "northGate",
                "immediateDanger": True,
                "accessBlocked": True,
                "staffOnScene": False,
                "contactAllowed": True,
            },
            classification=classification,
            signal_execution={
                "status": "delivered",
                "signal": {"id": "sig-1", "risk_level": "critical", "missing_info": ["guest count"]},
                "delivery": {"summary": {"channels": ["ops_console"]}},
                "customer_care_case": {"id": "case-1"},
            },
        )
        assert created["status"] == "operator_review"
        assert created["customer_report"]["redacted"] is True
        assert created["signal_id"] == "sig-1"
        assert created["customer_care_case_id"] == "case-1"
        assert created["lifecycle"]["allowed_next_actions"] == ["dispatch", "resolve", "false_alarm"]

        deduped = incidents.create_customer_emergency_incident(
            {"idempotencyKey": "incident-1", "text": "duplicate", "location": "North Gate"},
            classification=classification,
        )
        assert deduped["deduped"] is True
        assert deduped["id"] == created["id"]

        second = incidents.create_customer_emergency_incident(
            {"text": "Smoke near plaza 999999", "location": "South Plaza", "zoneId": "south", "accessBlocked": False},
            classification={"severity": "medium", "escalation_level": "watch", "requires_human_review": False},
            signal_execution={"signal": "bad", "delivery": "bad", "customer_care_case": "bad"},
        )
        assert second["status"] == "triaged"
        assert second["recommended_owner"] == "Guest Services"
        assert second["signal_id"] is None

        listed = incidents.list_customer_emergency_incidents(limit=10)
        assert listed["count"] == 2
        assert listed["summary"]["operator_review"] == 1
        assert listed["summary"]["critical_or_life_safety"] == 1
        assert incidents.list_customer_emergency_incidents(status="operator_review")["count"] == 1
        assert incidents.get_customer_emergency_incident(created["id"])["id"] == created["id"]
        assert incidents.get_customer_emergency_incident("missing") is None

        dispatched = incidents.update_customer_emergency_incident(created["id"], action="dispatch", actor="ops", note="Team sent")
        assert dispatched["status"] == "dispatched"
        assert dispatched["operator"]["notes"][0]["note"] == "Team sent"
        resolved = incidents.update_customer_emergency_incident(created["id"], action="resolve", actor="", note="")
        assert resolved["status"] == "resolved"
        assert resolved["lifecycle"]["allowed_next_actions"] == []

        for status, actions in {
            "submitted": ["acknowledge", "dispatch", "resolve", "false_alarm"],
            "triaged": ["acknowledge", "dispatch", "resolve", "false_alarm"],
            "operator_review": ["dispatch", "resolve", "false_alarm"],
            "dispatched": ["resolve"],
            "resolved": [],
        }.items():
            assert incidents.allowed_incident_actions(status) == actions

        audit = incidents.build_customer_emergency_audit_event(resolved, "operator_action", actor="ops", action="resolve", note="done", details={"ok": True})
        assert audit["incidentId"] == created["id"]
        assert audit["details"] == {"ok": True}
        assert audit["eventType"] == "operator_action"

        upserted = incidents.upsert_customer_emergency_incident({"_id": "manual-1", "status": "submitted", "idempotencyKey": "manual-key"})
        assert upserted["id"] == "manual-1"
        assert incidents.create_customer_emergency_incident({"idempotencyKey": "manual-key"}, classification={})["deduped"] is True

        with pytest.raises(ValueError):
            incidents.upsert_customer_emergency_incident({})
        with pytest.raises(ValueError):
            incidents.update_customer_emergency_incident(created["id"], action="bad", actor="ops")
        with pytest.raises(KeyError):
            incidents.update_customer_emergency_incident("missing", action="resolve", actor="ops")

        real_import = builtins.__import__

        def fail_mongo_import(name, *args, **kwargs):
            if name == "mongo_memory":
                raise RuntimeError("mongo unavailable")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_mongo_import)
        incidents.reset_customer_emergency_incidents()
        assert incidents.list_customer_emergency_incidents()["count"] == 0
    finally:
        incidents.reset_customer_emergency_incidents()


def test_executive_experience_artifacts_simulation_brief_and_review():
    import executive_experience_artifacts as artifacts

    assert artifacts._as_list("not-list") == []
    assert artifacts._as_list([1]) == [1]
    assert artifacts._safe_int("bad") == 0
    assert artifacts._month_sequence("bad", 1) == ["2026-03", "2026-04", "2026-05"]

    simulated = artifacts.simulated_executive_experience_documents(scenario="training-improves-recovery", months=4, end_month="2026-06")
    assert set(simulated) >= {"executive_guest_feedback_monthly", "executive_event_sentiment", "executive_staff_training_outcomes"}
    assert any(row["sentiment"] == "mixed" for row in simulated["executive_guest_feedback_monthly"])

    store: dict[str, list[dict[str, object]]] = {}

    def record_documents(collection, documents):
        store.setdefault(collection, []).extend(documents)
        return {"status": "stored", "collection": collection, "storedCount": len(documents)}

    def fetch_documents(collection, limit):
        return list(store.get(collection, []))[:limit]

    simulation = artifacts.simulate_executive_experience_evidence(
        record_documents=record_documents,
        fetch_documents=fetch_documents,
        scenario="unknown-scenario",
        months=3,
        end_month="2026-05",
    )
    assert simulation["status"] == "simulated"
    assert simulation["scenario"] == "unknown_scenario"
    assert simulation["storedCount"] > 0
    assert simulation["evidence"]["status"] in {"ready", "partial"}

    demo_import = artifacts.import_demo_executive_experience_evidence(record_documents=record_documents, fetch_documents=fetch_documents)
    assert demo_import["status"] == "imported"
    assert demo_import["storedCount"] > 0

    demo_docs = artifacts.demo_executive_experience_documents()
    demo_docs["executive_brief_artifacts"] = [
        {
            "artifactBaseId": "exec_monthly_guest_feedback_brief_2026_05",
            "artifactId": "exec_monthly_guest_feedback_brief_2026_05_v1",
            "_id": "exec_monthly_guest_feedback_brief_2026_05_v0",
            "version": 1,
        }
    ]

    def fetch_demo(collection, limit):
        return list(demo_docs.get(collection, []))[:limit]

    brief = artifacts.build_monthly_guest_feedback_brief(fetch_demo, requested_by_role="board_ops")
    assert brief["artifactId"] == "exec_monthly_guest_feedback_brief_2026_05_v2"
    assert brief["previousArtifactId"] == "exec_monthly_guest_feedback_brief_2026_05_v1"
    assert brief["requestedByRole"] == "board_ops"
    assert brief["containsDemoEvidence"] is True
    assert brief["reviewRequired"] is True
    assert brief["internalSummary"]["negativeThemes"]

    saved_records: list[dict[str, object]] = []

    def record_saved(collection, documents):
        saved_records.extend(documents)
        return {"status": "stored", "collection": collection, "storedCount": len(documents)}

    saved = artifacts.save_monthly_guest_feedback_brief(record_saved, fetch_demo, month="2026-05")
    assert saved["status"] == "stored"
    assert saved_records[0]["artifactType"] == "monthly_guest_feedback_brief"

    assert artifacts.review_executive_experience_artifact("a1", "bad", record_documents=record_saved, fetch_documents=lambda collection, limit: [])["status"] == "blocked"
    assert artifacts.review_executive_experience_artifact("missing", "approve", record_documents=record_saved, fetch_documents=lambda collection, limit: [])["status"] == "not_found"

    final_artifact = {**brief, "reviewerStatus": "approved"}
    final_result = artifacts.review_executive_experience_artifact(
        final_artifact["artifactId"],
        "reject",
        record_documents=record_saved,
        fetch_documents=lambda collection, limit: [final_artifact],
    )
    assert final_result["reason"].startswith("Artifact is already final")

    demo_block = artifacts.review_executive_experience_artifact(
        brief["artifactId"],
        "approve",
        record_documents=record_saved,
        fetch_documents=lambda collection, limit: [brief],
    )
    assert demo_block["status"] == "blocked"
    assert "Demo-backed" in demo_block["reason"]

    revised = artifacts.review_executive_experience_artifact(
        brief["artifactId"],
        "request-revision",
        note="Add live evidence.",
        reviewer_role="vp_guest",
        reviewer="casey",
        record_documents=record_saved,
        fetch_documents=lambda collection, limit: [brief],
    )
    assert revised["status"] == "stored"
    assert revised["artifact"]["reviewerStatus"] == "revision_requested"
    assert revised["artifact"]["reviewRequired"] is True
    assert revised["artifact"]["reviewEvents"][0]["action"] == "request_revision"

    approved = artifacts.review_executive_experience_artifact(
        brief["artifactId"],
        "approve",
        note="Demo approval for unit test.",
        allow_demo_approval=True,
        record_documents=record_saved,
        fetch_documents=lambda collection, limit: [{**brief, "containsDemoEvidence": True, "reviewEvents": [{"action": "prior"}]}],
    )
    assert approved["status"] == "stored"
    assert approved["artifact"]["status"] == "approved_for_board_use"
    assert approved["artifact"]["reviewRequired"] is False
    assert len(approved["artifact"]["reviewEvents"]) == 2


def test_executive_experience_artifacts_default_mongo_import_paths(monkeypatch):
    import executive_experience_artifacts as artifacts

    demo_docs = artifacts.demo_executive_experience_documents()
    demo_docs["executive_brief_artifacts"] = []
    recorded: dict[str, list[dict[str, object]]] = {}

    fake_mongo = types.ModuleType("mongo_memory")

    def fake_record(collection, documents):
        recorded.setdefault(collection, []).extend(documents)
        return {"status": "queued" if collection == "executive_brief_artifacts" else "stored", "collection": collection, "storedCount": len(documents)}

    def fake_fetch(collection, limit):
        if collection == "executive_brief_artifacts" and recorded.get(collection):
            return list(recorded[collection])[:limit]
        return list(demo_docs.get(collection, []))[:limit]

    fake_mongo.record_executive_experience_documents = fake_record
    fake_mongo.get_latest_memory_documents_fast = fake_fetch
    monkeypatch.setitem(sys.modules, "mongo_memory", fake_mongo)

    simulated = artifacts.simulate_executive_experience_evidence(months=3)
    assert simulated["status"] == "simulated"
    assert simulated["storedCount"] > 0

    imported = artifacts.import_demo_executive_experience_evidence()
    assert imported["status"] == "imported"
    assert imported["storedCount"] > 0

    brief = artifacts.build_monthly_guest_feedback_brief(month="2026-05")
    assert brief["month"] == "2026-05"

    saved = artifacts.save_monthly_guest_feedback_brief(month="2026-05")
    assert saved["status"] == "queued"
    assert saved["persistence"]["collection"] == "executive_brief_artifacts"

    unsupported = artifacts.review_executive_experience_artifact("missing", "unsupported")
    assert unsupported["status"] == "blocked"
    assert unsupported["allowedActions"] == ["approve", "reject", "request_revision"]


def test_controlled_training_generation_and_eval_workflow(tmp_path, monkeypatch):
    import controlled_training_eval
    import controlled_training_generation as generation

    monkeypatch.setenv("PARKPULSE_CONTROLLED_TRAINING_ARTIFACT_DIR", str(tmp_path))

    fake_mongo = types.ModuleType("mongo_memory")
    durable_docs: list[dict[str, object]] = []
    fake_mongo.record_controlled_training_eval = lambda report: durable_docs.append(report) or {"status": "stored", "id": report["id"]}
    fake_mongo.get_latest_controlled_training_eval = lambda: durable_docs[-1] if durable_docs else None
    monkeypatch.setitem(sys.modules, "mongo_memory", fake_mongo)

    training_readiness = {
        "status": "ready",
        "summary": {"open_review_count": 0},
        "agents": {
            agent_id: {
                "status": "ready",
                "model_training_ready": True,
                "eval_generation_ready": True,
                "recommended_training_mode": "offline",
                "evidence": {"source": "unit"},
            }
            for agent_id in generation.TRAINING_AGENT_ORDER
        },
    }
    actual_training = {
        "sample_count": "3",
        "training_rows": [
            {"id": "row-1", "scenario_key": "food_spike", "policy": "reroute", "reward": 1.25, "label": "improved", "features": {"density": 80}, "source": "outcome"},
            {"id": "row-2", "stateScenario": {"key": "ride_down"}, "policy_id": "dispatch", "reward_delta": 0.75, "outcome_label": "contained"},
            {"id": "row-3", "scenario": "weather_alert", "mode": "notify", "fitness": 0.5},
        ],
    }
    pack = generation.generate_controlled_training_pack(
        customer_details={
            "recommended_public_options": {"best_ride": {"name": "Story Garden"}, "best_food": {"name": "Harbor Cafe"}},
            "data_quality": {"status": "ready", "score": 0.92},
        },
        training_readiness=training_readiness,
        review_label_pipeline={
            "decided": [
                {
                    "id": "ops-chat-1",
                    "input_summary": "Operator asks for tone-safe disruption copy.",
                    "training_scope": "ops_chat_eval",
                    "proposed_label": "safe_response",
                    "decision": {"decision": "approved"},
                    "source": "review",
                }
            ]
        },
        review_label_decisions={
            "summary": {"approved_label_count": "2"},
            "rows": [
                {
                    "id": "label-1",
                    "candidate_id": "cand-1",
                    "agent_id": "customer_agent",
                    "training_scope": "customer_supervised",
                    "eligible_for_supervised_training": True,
                    "candidate_snapshot": {"input_summary": "guest request", "evidence": {"source": "public"}},
                    "final_label": "grounded",
                    "decision": "approved",
                    "reviewer": "qa",
                },
                {"id": "label-rl", "agent_id": "rl_action_policy", "eligible_for_supervised_training": True},
                "bad-row",
            ],
        },
        actual_training=actual_training,
        live_feed_health={"feeds": [{"source": "weather", "status": "ready", "confidence": 0.91, "age_seconds": 2, "required": True}, "bad-row"]},
        max_examples=20,
        write_artifacts=True,
    )

    assert pack["status"] == "generated"
    assert pack["summary"]["role_scope_count"] == len(generation.TRAINING_AGENT_ORDER)
    assert pack["summary"]["approved_review_label_count"] == 2
    assert pack["artifacts"]["status"] == "written"
    assert {row["agent_id"] for row in pack["examples"]} == set(generation.TRAINING_AGENT_ORDER)
    assert all(row["uses_seed_data"] is False for row in pack["examples"])

    latest = generation.latest_controlled_training_pack()
    assert latest["id"] == pack["id"]
    assert latest["artifacts"]["latest_manifest_path"].endswith(".manifest.json")

    eval_report = controlled_training_eval.run_controlled_training_eval(pack, write_artifact=True)
    assert eval_report["status"] == "passed"
    assert eval_report["decision"] == "allow_offline_training_generation"
    assert eval_report["artifacts"]["durable"]["status"] == "stored"
    assert controlled_training_eval.latest_controlled_training_eval()["artifacts"]["durable_storage"] == "mongodb"
    assert controlled_training_eval.offline_training_eval_gate_passed()["allowed"] is True
    durable_doc = controlled_training_eval._durable_eval_document(eval_report)
    assert durable_doc["role_results"][0]["failure_reasons"] == []


def test_controlled_training_failure_edges(tmp_path, monkeypatch):
    import controlled_training_eval
    import controlled_training_generation as generation

    monkeypatch.setenv("PARKPULSE_CONTROLLED_TRAINING_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(controlled_training_eval, "_latest_durable_eval", lambda: None)
    real_write_durable_eval = controlled_training_eval._write_durable_eval
    real_latest_durable_eval = controlled_training_eval._latest_durable_eval
    monkeypatch.setattr(controlled_training_eval, "_write_durable_eval", lambda report: {"status": "skipped", "mode": "unit_no_durable_write"})

    missing_dir = tmp_path / "missing"
    monkeypatch.setenv("PARKPULSE_CONTROLLED_TRAINING_ARTIFACT_DIR", str(missing_dir))
    assert generation.latest_controlled_training_pack()["status"] == "empty"
    assert controlled_training_eval.latest_controlled_training_eval()["status"] == "empty"
    monkeypatch.setenv("PARKPULSE_CONTROLLED_TRAINING_ARTIFACT_DIR", str(tmp_path))

    assert generation.latest_controlled_training_pack()["status"] == "empty"
    assert controlled_training_eval.latest_controlled_training_eval()["status"] == "empty"
    invalid_manifest = tmp_path / "bad.manifest.json"
    invalid_manifest.write_text("[]", encoding="utf-8")
    assert generation.latest_controlled_training_pack()["status"] == "error"
    invalid_eval = tmp_path / "bad.eval.json"
    invalid_eval.write_text("[]", encoding="utf-8")
    assert controlled_training_eval.latest_controlled_training_eval()["status"] == "error"
    invalid_manifest.unlink()
    invalid_eval.unlink()

    hold_training = {"status": "blocked", "summary": {"open_review_count": "3"}, "agents": {"customer_agent": {"eval_generation_ready": False}}}
    blocked_pack = generation.generate_controlled_training_pack(
        customer_details={},
        training_readiness=hold_training,
        review_label_pipeline={},
        review_label_decisions={},
        actual_training={},
        live_feed_health={},
        max_examples=0,
        write_artifacts=False,
    )
    assert blocked_pack["status"] == "blocked"
    assert "Open review queue remains non-zero: 3." in blocked_pack["readiness_issues"]
    assert blocked_pack["artifacts"]["status"] == "not_written"
    assert generation._generation_mode("rl_action_policy", True, False) == "offline_rl_reward_manifest"
    assert generation._generation_mode("scan_agent", False, True) == "eval_generation_only"
    assert generation._scope_ready([], "missing") is False
    assert generation._scenario_key({"stateScenario": {"key": "state-key"}}) == "state-key"
    assert generation._scenario_key({"scenario": "fallback"}) == "fallback"
    assert generation._scenario_key({}) is None
    assert generation._int("", 7) == 7
    assert generation._int("bad", 7) == 7
    assert generation._outcome_rows_for_agent(["bad-row", {"scenario_key": "x", "policy": "p"}], "react_agent", "scope", reward=False)[0]["input"]["scenario_key"] == "x"
    assert generation._ops_chat_eval_examples({"decided": ["bad-row"]}, [{"agent_id": "ops_chat", "generation_mode": "eval_generation_only"}]) == []

    bounded = generation._bounded_examples(
        [
            generation._example(
                agent_id="customer_agent",
                split="eval",
                training_scope="scope",
                source="customer_public_data_feed",
                input_payload={"i": 1},
                expected_output={"label": "ok"},
                evidence={},
                eligible_for_supervised_training=False,
                eligible_for_reward=False,
            ),
            generation._example(
                agent_id="scan_agent",
                split="eval",
                training_scope="scope",
                source="live_feed_health",
                input_payload={"i": 2},
                expected_output={"label": "ok"},
                evidence={},
                eligible_for_supervised_training=False,
                eligible_for_reward=False,
            ),
        ],
        1,
    )
    assert len(bounded) == 1

    bad_common = {
        "id": "bad",
        "agent_id": "customer_agent",
        "split": "eval",
        "training_scope": "",
        "source": "internal_note",
        "input": {},
        "expected_output": {},
        "eligible_for_reward": True,
        "uses_seed_data": True,
        "labels_or_reward_changed": True,
        "llm_used_for_reward_or_label": True,
    }
    bad_customer = controlled_training_eval._score_role("customer_agent", [bad_common])
    assert bad_customer["passed"] is False
    assert "Customer examples must never be reward rows." in bad_customer["failure_reasons"]

    bad_scan = controlled_training_eval._score_role(
        "scan_agent",
        [
            {
                **bad_common,
                "agent_id": "scan_agent",
                "training_scope": "scan",
                "source": "live_feed_health",
                "input": {"status": "ready", "confidence": 0.2},
                "eligible_for_reward": False,
                "uses_seed_data": False,
                "labels_or_reward_changed": False,
                "llm_used_for_reward_or_label": False,
            }
        ],
    )
    assert "Trusted live-feed eval requires confidence >= 0.7." in bad_scan["failure_reasons"]
    scan_reward = controlled_training_eval._score_role(
        "scan_agent",
        [{**bad_common, "agent_id": "scan_agent", "training_scope": "scan", "source": "unexpected", "eligible_for_reward": True, "uses_seed_data": False, "labels_or_reward_changed": False, "llm_used_for_reward_or_label": False}],
    )
    assert "Scan examples must not be reward rows." in scan_reward["failure_reasons"]
    assert "Scan example must come from live feed health or approved review label." in scan_reward["failure_reasons"]

    bad_ops = controlled_training_eval._score_role(
        "react_agent",
        [
            {
                **bad_common,
                "agent_id": "react_agent",
                "training_scope": "react",
                "source": "observed_outcome_training_row",
                "input": {},
                "eligible_for_reward": False,
                "uses_seed_data": False,
                "labels_or_reward_changed": False,
                "llm_used_for_reward_or_label": False,
            }
        ],
    )
    assert "Observed outcome example is missing scenario_key." in bad_ops["failure_reasons"]
    assert "Observed outcome example is missing selected policy." in bad_ops["failure_reasons"]
    approved_ops_missing_label = controlled_training_eval._score_role(
        "react_agent",
        [{**bad_common, "agent_id": "react_agent", "training_scope": "react", "source": "approved_review_label_decision", "expected_output": {}, "eligible_for_reward": True, "uses_seed_data": False, "labels_or_reward_changed": False, "llm_used_for_reward_or_label": False}],
    )
    assert "React/proactive eval examples must not be reward rows." in approved_ops_missing_label["failure_reasons"]
    assert "Approved react/proactive supervised label is missing an expected label." in approved_ops_missing_label["failure_reasons"]
    unexpected_ops_source = controlled_training_eval._score_role(
        "proactive_agent",
        [{**bad_common, "agent_id": "proactive_agent", "training_scope": "proactive", "source": "unexpected", "input": {"scenario_key": "x", "policy": "p"}, "eligible_for_reward": False, "uses_seed_data": False, "labels_or_reward_changed": False, "llm_used_for_reward_or_label": False}],
    )
    assert "React/proactive examples require observed outcome rows." in unexpected_ops_source["failure_reasons"]

    bad_rl = controlled_training_eval._score_role(
        "rl_action_policy",
        [
            {
                **bad_common,
                "agent_id": "rl_action_policy",
                "training_scope": "rl",
                "source": "approved_review_label_decision",
                "expected_output": {"reward": "bad", "reward_source": "llm"},
                "eligible_for_reward": False,
                "uses_seed_data": False,
                "labels_or_reward_changed": False,
                "llm_used_for_reward_or_label": False,
            }
        ],
    )
    assert "RL/action-policy rows must come from observed outcome rows." in bad_rl["failure_reasons"]
    assert "RL/action-policy gate requires measured reward rows from observed outcomes." in bad_rl["failure_reasons"]
    bad_ops_chat = controlled_training_eval._score_role(
        "ops_chat",
        [{**bad_common, "agent_id": "ops_chat", "training_scope": "ops", "source": "review_label_pipeline_decided", "expected_output": {}, "eligible_for_reward": True, "uses_seed_data": False, "labels_or_reward_changed": False, "llm_used_for_reward_or_label": False}],
    )
    assert "Ops chat examples must never be reward rows." in bad_ops_chat["failure_reasons"]
    assert "Ops chat eval requires expected safety/style label or decision." in bad_ops_chat["failure_reasons"]

    assert controlled_training_eval._score_role("unknown_agent", [{**bad_common, "agent_id": "unknown_agent", "training_scope": "x"}])["status"] == "failed"
    assert controlled_training_eval._role_checks("unknown") == ["known role scope"]
    assert controlled_training_eval._float("bad", 4.5) == 4.5
    assert controlled_training_eval._float("", 4.5) == 4.5

    failing_report = controlled_training_eval.run_controlled_training_eval(
        {"id": "bad-pack", "status": "blocked", "examples": [], "uses_seed_data": True, "labels_or_reward_changed": True, "llm_used_for_reward_or_label": True},
        write_artifact=False,
    )
    assert failing_report["status"] == "failed"
    assert "Controlled pack status is blocked." in failing_report["readiness_issues"]
    controlled_training_eval._write_eval_artifact(failing_report)
    scoped = controlled_training_eval.offline_training_eval_gate_passed(["customer_agent"])
    assert scoped["allowed"] is False
    assert scoped["status"] == "scoped_failed"
    no_roles = controlled_training_eval.offline_training_eval_gate_passed()
    assert no_roles["allowed"] is False

    scoped_pass_report = {
        **failing_report,
        "status": "failed",
        "role_results": [
            {"agent_id": "customer_agent", "passed": True, "score": 100, "min_score": 80},
            {"agent_id": "scan_agent", "passed": False, "score": 0, "min_score": 80},
        ],
        "readiness_issues": ["scan_agent failed eval gate: score 0/80."],
    }
    controlled_training_eval._write_eval_artifact(scoped_pass_report)
    scoped_pass = controlled_training_eval.offline_training_eval_gate_passed(["customer_agent"])
    assert scoped_pass["allowed"] is True
    assert scoped_pass["status"] == "scoped_passed"

    raising_mongo = types.ModuleType("mongo_memory")
    raising_mongo.record_controlled_training_eval = lambda report: (_ for _ in ()).throw(RuntimeError("durable down"))
    raising_mongo.get_latest_controlled_training_eval = lambda: (_ for _ in ()).throw(RuntimeError("latest down"))
    monkeypatch.setitem(sys.modules, "mongo_memory", raising_mongo)
    assert real_write_durable_eval(failing_report)["status"] == "skipped"
    assert real_latest_durable_eval() is None


def test_controlled_training_last_edge_branches(monkeypatch):
    import controlled_training_eval
    import controlled_training_generation as generation

    unknown_example = generation._example(
        agent_id="unknown_agent",
        split="eval",
        training_scope="unknown",
        source="unit",
        input_payload={},
        expected_output={"label": "ok"},
        evidence={},
        eligible_for_supervised_training=False,
        eligible_for_reward=False,
    )
    assert generation._bounded_examples([unknown_example], 1) == [unknown_example]

    raising_mongo = types.ModuleType("mongo_memory")
    raising_mongo.get_latest_controlled_training_eval = lambda: (_ for _ in ()).throw(RuntimeError("latest unavailable"))
    monkeypatch.setitem(sys.modules, "mongo_memory", raising_mongo)
    assert controlled_training_eval._latest_durable_eval() is None


def test_review_label_pipeline_edges_and_storage(tmp_path, monkeypatch):
    import review_label_pipeline as labels

    log_path = tmp_path / "labels.jsonl"
    monkeypatch.setenv("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", str(log_path))
    monkeypatch.delenv("PARKPULSE_REVIEW_LABEL_STORAGE", raising=False)
    monkeypatch.delenv("PARKPULSE_LIVE_FEED_STORAGE", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    labels._MONGO_CLIENT = None

    assert labels.record_review_label_decision({})["readiness_issues"] == ["candidate_id is required."]
    assert "decision must be" in labels.record_review_label_decision({"candidate_id": "c1", "decision": "bad"})["readiness_issues"][0]
    assert labels.record_review_label_decision({"candidate_id": "c1", "decision": "approve_label"})["readiness_issues"] == ["final_label is required for approved or edited labels."]
    assert labels.review_label_decision_ledger()["status"] == "empty"
    assert labels._mongo_client() is None
    assert labels._write_mongo_decision({"id": "no-client"}) is False
    assert labels._read_mongo_decisions() == []

    pipeline = labels.build_review_label_pipeline(
        customer_details={"data_quality": "bad", "feed_contract": "bad", "recommended_public_options": "bad"},
        training_readiness={"agents": {"bad": "skip", "ready": {"status": "ready", "model_training_ready": True, "eval_generation_ready": False}}},
        review_ledger={"open_reviews": ["skip", {"id": "review-1", "priority": "medium", "event": {"id": "event-1", "confidence": 0.9}}]},
        live_feed_health={"feeds": ["skip", {"source": "ready-feed", "status": "ready"}, {"source": "stale-feed", "status": "stale", "confidence": 0.8, "readiness_issues": ["old"]}]},
        limit=0,
    )
    assert pipeline["summary"]["candidate_count"] >= 3
    assert len(pipeline["candidates"]) >= 1
    assert labels._customer_candidates({}) == []
    assert labels._customer_candidates({"data_quality": {}, "feed_contract": {}, "recommended_public_options": {}}) == []
    production_customer = labels._customer_candidates(
        {
            "data_quality": {"status": "production_ready", "score": 100},
            "feed_contract": {"production_publishable": True},
            "recommended_public_options": {"best_ride": {"name": "Ride"}, "best_food": {"name": "Food"}},
        }
    )
    assert production_customer[0]["priority"] == "high"
    assert production_customer[0]["proposed_label"] == "customer_recommendation_grounded"

    closed = labels._attach_decision(pipeline["candidates"][0], {pipeline["candidates"][0]["id"]: {"eligible_for_supervised_training": False, "decision": "reject_label"}})
    assert closed["review_status"] == "closed_not_training"
    assert labels._public_candidate_snapshot(closed)["id"] == closed["id"]
    assert labels._candidate_evidence_key("review_training_ledger", {"case_id": "case-1", "event": {"id": "event-2"}}) == "case-1"
    assert labels._candidate_evidence_key("review_training_ledger", {"event": {"source_event_id": "event-3"}}) == "event-3"
    assert labels._candidate_evidence_key("live_feed_health", {"source": "weather", "status": "stale"}) == "weather:stale:"

    recorded = labels.record_review_label_decision(
        {
            "candidate": production_customer[0],
            "candidate_id": production_customer[0]["id"],
            "decision": "edit_label",
            "finalLabel": "edited_label",
            "reviewer": "reviewer",
            "note": "edited",
        }
    )
    assert recorded["status"] == "recorded"
    auto_recorded = labels.auto_label_recommended_candidates({"candidates": [production_customer[0]]}, confidence_threshold=0.1)
    assert auto_recorded["recorded_count"] == 1

    assert labels._recommendation_metadata(0.6, "x")["confidence_status"] == "medium"
    assert labels._recommendation_metadata(None, "x")["confidence_status"] == "low"
    assert labels._recommendation_confidence({"recommendation": "bad"}) == 0.0
    assert labels._bounded_confidence("bad") == 0.0
    assert labels._customer_confidence({"status": "production_ready", "score": 30}, {"production_publishable": True}) == 0.9
    assert labels._customer_confidence({"status": "partial", "score": 50}, {}) == 0.6
    assert labels._customer_confidence({}, {}) == 0.4
    assert labels._training_confidence({"status": "blocked", "model_training_ready": False, "blockers": ["x"]}) == 0.86
    assert labels._training_confidence({"status": "ready", "model_training_ready": True}) == 0.8
    assert labels._training_confidence({"status": "ready"}) == 0.62
    assert labels._training_confidence({}) == 0.45
    assert labels._live_review_confidence({"priority": "critical", "reason": "low confidence"}, {"confidence": 0.9}) == 0.55
    assert labels._live_review_confidence({"priority": "critical", "reason": ""}, {"confidence": 0.88}) == 0.88
    assert labels._live_review_confidence({"priority": "low", "reason": ""}, {"confidence": 0.8}) == 0.8
    assert labels._feed_quality_confidence({"status": "weak", "confidence": 0.4}) == 0.4
    assert labels._feed_quality_confidence({"status": "ready", "confidence": 0.8}) == 0.8
    assert labels._priority_rank("critical") == 0
    assert labels._priority_rank("unknown") == 5

    auto = labels.auto_label_recommended_candidates(
        {
            "candidates": [
                "skip",
                {"id": "", "proposed_label": "ok", "recommendation": {"confidence": 1.0}},
                {"id": "low", "proposed_label": "ok", "recommendation": {"confidence": 0.1}},
            ]
        },
        confidence_threshold=2.0,
    )
    assert auto["status"] == "no_high_confidence_candidates"
    assert auto["confidence_threshold"] == 1.0
    assert auto["skipped_count"] == 2

    log_path.write_text('{"candidate_id":"old","eligible_for_supervised_training":true}\nnot-json\n[]\n', encoding="utf-8")
    latest = labels._latest_decisions()
    assert latest["old"]["candidate_id"] == "old"
    assert labels._read_jsonl(str(tmp_path / "missing.jsonl")) == []
    assert labels._read_jsonl(str(log_path), limit=5)[0]["candidate_id"] == "old"
    assert labels._strip_secret("'mongodb://host/db'") == "mongodb://host/db"
    assert labels._strip_secret(" plain ") == "plain"
    assert labels._int_env("MISSING_INT_ENV", 9) == 9
    monkeypatch.setenv("MISSING_INT_ENV", "bad")
    assert labels._int_env("MISSING_INT_ENV", 9) == 9
    monkeypatch.setenv("MONGODB_DATABASE", "configured_db")
    assert labels._mongo_database_name() == "configured_db"
    monkeypatch.delenv("MONGODB_DATABASE", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DIRECT_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    assert labels._mongo_database_name() == "parkpulse"
    assert labels._read_jsonl(str(tmp_path), limit=5) == []

    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows

        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, _limit):
            return self

        def __iter__(self):
            return iter(self.rows)

    class FakeCollection:
        def __init__(self, rows=None, fail=False):
            self.rows = rows or []
            self.fail = fail
            self.writes = []

        def replace_one(self, *args, **kwargs):
            if self.fail:
                raise RuntimeError("write failed")
            self.writes.append((args, kwargs))

        def find(self, *args, **kwargs):
            if self.fail:
                raise RuntimeError("read failed")
            return FakeCursor(self.rows)

    class FakeDb:
        def __init__(self, collection):
            self.review_label_decisions = collection

    class FakeClient:
        def __init__(self, uri, **kwargs):
            self.uri = uri
            self.kwargs = kwargs
            self.collection = FakeCollection([{"_id": "mongo-1", "candidate_id": "mongo-1"}, "skip"])

        def __getitem__(self, _name):
            return FakeDb(self.collection)

    fake_mongo = types.ModuleType("mongo_memory")
    fake_mongo.MongoClient = FakeClient
    fake_mongo._ensure_mongo_driver = lambda: True
    fake_mongo._normalized_mongodb_uri = lambda uri: f"normalized:{uri}"
    monkeypatch.setitem(sys.modules, "mongo_memory", fake_mongo)
    monkeypatch.setenv("PARKPULSE_REVIEW_LABEL_STORAGE", "mongodb")
    monkeypatch.setenv("MONGODB_URI", '"mongodb://example.com/from_uri"')
    monkeypatch.delenv("MONGODB_DATABASE", raising=False)
    labels._MONGO_CLIENT = None

    assert labels._storage_mode() == "mongodb"
    assert labels._mongo_uri() == "mongodb://example.com/from_uri"
    assert labels._mongo_database_name() == "from_uri"
    client = labels._mongo_client()
    assert client.uri == "normalized:mongodb://example.com/from_uri"
    assert labels._write_mongo_decision({"id": "mongo-write"}) is True
    labels._append_jsonl(str(tmp_path / "mongo-only.jsonl"), {"id": "mongo-append"})
    assert not (tmp_path / "mongo-only.jsonl").exists()
    assert labels._read_mongo_decisions(limit="bad") == []
    assert labels._read_mongo_decisions(limit=5) == [{"candidate_id": "mongo-1"}]
    assert labels._read_jsonl(str(log_path), limit=5) == [{"candidate_id": "mongo-1"}]

    client.collection.fail = True
    assert labels._write_mongo_decision({"id": "fail"}) is False
    assert labels._read_mongo_decisions() == []
    labels._MONGO_CLIENT = None
    fake_mongo._ensure_mongo_driver = lambda: False
    assert labels._mongo_client() is None
    fake_mongo._ensure_mongo_driver = lambda: True
    fake_mongo.MongoClient = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("connect failed"))
    labels._MONGO_CLIENT = None
    assert labels._mongo_client() is None
    sentinel = object()

    class FakeLock:
        def __enter__(self):
            labels._MONGO_CLIENT = sentinel

        def __exit__(self, *_args):
            return False

    labels._MONGO_CLIENT = None
    monkeypatch.setattr(labels, "_MONGO_CLIENT_LOCK", FakeLock())
    assert labels._mongo_client() is sentinel


def test_main_role_auth_identity_and_surface_helpers(monkeypatch):
    monkeypatch.setenv("PARKPULSE_ROLE_AUTH_SECRET", " local-secret ")
    monkeypatch.setenv("PARKPULSE_ROLE_SESSION_ISSUER_KEY", "issuer-key")
    monkeypatch.setenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", "false")
    monkeypatch.setenv("PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION", "false")

    assert main._request_headers({"headers": [(b"X-Role", b"ops_team"), ("Bad", object())]})["x-role"] == "ops_team"
    assert main._truthy(None, True) is True
    assert main._truthy("yes") is True
    assert main._role_auth_secret() == "local-secret"
    assert main._signed_role_required() is False
    assert main._issuer_key_matches("issuer-key") is True
    assert main._issuer_key_matches("wrong") is False
    assert main._extract_role_token({"authorization": "Bearer abc"}) == "abc"
    assert main._extract_role_token({"x-parkpulse-role-token": "explicit"}) == "explicit"

    token = main.sign_role_session("operator-1", "ops_team", main._role_auth_secret(), ttl_seconds=300)
    signed = main._request_role_context({"headers": [(b"x-parkpulse-role-token", token.encode())]})
    assert signed["authenticated"] is True
    assert signed["role"] == "ops_team"

    monkeypatch.setattr(
        main,
        "verify_external_role_identity",
        lambda headers, default_role="ops_team": {
            "status": "authenticated",
            "authenticated": True,
            "auth_method": "external_test",
            "role": "ml_ops_admin",
            "subject": "admin@example.com",
        },
    )
    external = main._request_role_context({"headers": [(b"x-test", b"1")]})
    assert external["auth_method"] == "external_test"

    monkeypatch.setattr(main, "verify_external_role_identity", lambda headers, default_role="ops_team": {"status": "missing", "authenticated": False})
    monkeypatch.setenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", "true")
    denied = main._request_role_context({"headers": []}, {"role": "customer"})
    assert denied["authenticated"] is False
    assert denied["role"] == "customer"
    assert main._authorization_response({"reason": "nope"})["status"] == "blocked"
    assert main._role_authorization_payload({})["status"] == "error"
    assert main._role_authorization_payload({"role": "ops_team", "capability": "read_ops_evidence"})["mode"] == "role_authorization_check"

    monkeypatch.setattr(
        main,
        "identity_provider_readiness",
        lambda: {
            "external_identity_ready": True,
            "external_identity_providers": {"oidc_proxy": True},
            "role_mapping": {"ops_emails": 1},
        },
    )
    monkeypatch.setenv("PARKPULSE_ROLE_AUTH_SECRET", "prod-secret")
    assert main._identity_readiness_payload()["status"] == "production_ready"
    surfaces = main._role_product_surfaces_payload()
    assert surfaces["role_count"] >= 4
    assert {row["role"] for row in surfaces["surfaces"]} >= {"customer", "ops_team", "ml_ops_admin"}


def test_main_live_feed_preflight_refresh_and_worker_helpers(monkeypatch):
    main._live_feed_health_cache.clear()
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_HEALTH_CACHE_TTL_SECONDS", "30")

    async def fake_state_lite():
        return {"guestFlow": {"activeScenario": {"key": "ride_down"}}}

    monkeypatch.setattr(main, "_fast_park_state_lite", fake_state_lite)
    calls = {"health": 0}

    def fake_live_feed_health(state, limit=120):
        calls["health"] += 1
        return {
            "status": "ready",
            "summary": {"ready_feed_count": 4},
            "feeds": [
                {"source": "weather", "status": "stale", "age_seconds": 95, "max_stale_seconds": 100, "readiness_issues": ["old"]},
                {"source": "ride_ops", "status": "ready", "age_seconds": 99, "max_stale_seconds": 100},
                {"source": "guest_flow", "status": "error", "age_seconds": 5, "max_stale_seconds": 100, "readiness_issues": ["down"]},
                {"source": "unknown", "status": "stale", "age_seconds": 200, "max_stale_seconds": 100},
            ],
        }

    monkeypatch.setattr(main, "live_feed_health", fake_live_feed_health)
    first = run(main._live_feed_health_payload(limit=20))
    second = run(main._live_feed_health_payload(limit=20))
    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert calls["health"] == 1

    raw_state = {"state": "raw"}

    async def fake_raw_state():
        return raw_state

    monkeypatch.setattr(main, "_raw_fast_park_state_for_feed_load", fake_raw_state)
    monkeypatch.setattr(main, "_queue_live_weather_refresh", lambda reason: {"status": "queued", "reason": reason})
    monkeypatch.setattr(main, "ingest_live_ride_ops_feed", lambda state: {"status": "ready", "source": "ride_ops", "state": state})
    monkeypatch.setattr(main, "ingest_live_guest_flow_feed", lambda state: {"status": "error", "readiness_issues": ["guest flow offline"]})

    refresh = run(
        main._refresh_due_live_feeds_payload(
            {
                "sources": ["weather", "ride_ops", "guest_flow", "unknown"],
                "stale_only": False,
                "refresh_margin_seconds": "bad",
            }
        )
    )
    assert refresh["status"] == "error"
    assert "weather" in refresh["queued_sources"]
    assert "ride_ops" in refresh["refreshed_sources"]
    assert any("guest_flow" in issue for issue in refresh["readiness_issues"])

    no_refresh = run(main._training_live_feed_preflight_payload({"refreshLiveFeeds": "false"}))
    assert no_refresh["status"] == "no_due_feeds"

    async def fake_refresh_due(payload):
        return {
            "status": "refreshed",
            "refreshed_sources": ["ride_ops"],
            "queued_sources": [],
            "result_count": 1,
            "before": {"ready_feed_count": 2},
            "after": {"ready_feed_count": 3},
            "after_feeds": [{"source": "ride_ops", "status": "ready"}, {"source": "weather", "status": "error", "readiness_issues": ["old"]}],
            "readiness_issues": [],
        }

    monkeypatch.setattr(main, "_refresh_due_live_feeds_payload", fake_refresh_due)
    preflight = run(main._training_live_feed_preflight_payload({"liveFeedSources": ["ride_ops", "weather"]}))
    assert preflight["status"] == "needs_review"
    assert "weather: old" in preflight["readiness_issues"]

    async def fake_auto_label():
        return {"status": "labeled", "approved": 2}

    monkeypatch.setattr(main, "_auto_label_high_confidence_current_candidates", fake_auto_label)
    tick = run(main._live_feed_refresh_worker_tick())
    assert tick["status"] == "ready"
    assert tick["auto_label"]["status"] == "labeled"


def test_main_memory_trace_platform_and_training_helpers(monkeypatch):
    monkeypatch.setattr(main, "_park_understanding_memory_log_path", lambda: "/tmp/park_understanding_memory.jsonl")
    monkeypatch.setattr(main, "_causal_reasoning_memory_log_path", lambda: "/tmp/causal_reasoning_memory.jsonl")
    monkeypatch.setattr(main, "_park_retrieval_quality_log_path", lambda: "/tmp/retrieval_quality.jsonl")
    monkeypatch.setattr(main, "_heartbeat_action_log_path", lambda: "/tmp/actions.jsonl")
    monkeypatch.setattr(main, "_heartbeat_explanation_log_path", lambda: "/tmp/explanations.jsonl")
    monkeypatch.setattr(main, "_outcome_error_ledger_log_path", lambda: "/tmp/outcomes.jsonl")
    monkeypatch.setattr(main, "_role_authorization_log_path", lambda: "/tmp/auth.jsonl")

    def fake_records(path, limit=240):
        if "park_understanding" in path:
            return [{"park_dynamics_graph": {"nodes": [{"id": "n1"}], "edges": [{"from": "n1", "to": "n2"}]}}]
        if "causal" in path:
            return [{"scenario_key": "ride_down", "mechanism_ids": ["queue_spillback", "queue_spillback", "reroute"]}]
        if "retrieval" in path:
            return [{"summary": {"pass_rate": 0.8}}]
        if "actions" in path:
            return [{"id": "a1", "scenario_key": "ride_down", "candidate": {"target": "ride", "action": "reroute", "score": 84}, "policy_gate": {"gate_status": "allowed", "allowed": True, "findings": ["ok"]}, "executed": True}]
        if "explanations" in path:
            return [{"action_id": "a1", "status": "ready", "explanation": {"headline": "why"}, "llm": {"status": "skipped"}}]
        if "outcomes" in path:
            return [{"source_action_id": "a1", "label": "better", "failure_class": "none", "promotion_impact": "neutral", "training": {"eligible": True}}]
        if "auth" in path:
            return [{"role": "ops_team", "allowed": True}]
        return []

    monkeypatch.setattr(main, "_recent_jsonl_records", fake_records)
    graph = main._deep_memory_graph_payload(limit=500)
    assert graph["status"] == "ready"
    assert graph["graph"]["node_count"] == 1
    assert graph["top_mechanisms"][0][0] == "queue_spillback"
    traces = main._decision_traces_payload(limit=3)
    assert traces["status"] == "ready"
    assert traces["traces"][0]["explanation"]["headline"] == "why"

    def actual_training_status(min_rows, run_gcp_training):
        return {
            "status": "ready",
            "sample_count": min_rows,
            "model_ops": {
                "promotion_gate": {"status": "pass"},
                "slice_rollback_ledger": {"rollback_count": 0},
                "promoted_slice_policy": {"id": "p1"},
            },
        }

    def promoted_slice_policy_status():
        return {"artifact": {"id": "p2"}, "rollback_ledger": {"rollback_count": 1}}

    import park_actual_training

    monkeypatch.setattr(park_actual_training, "actual_training_status", actual_training_status)
    monkeypatch.setattr(park_actual_training, "promoted_slice_policy_status", promoted_slice_policy_status)
    promotion = run(main._promotion_governance_payload())
    assert promotion["status"] == "pass"
    assert promotion["promoted_slice_policy"]["id"] == "p2"

    monkeypatch.setattr(main, "_identity_readiness_payload", lambda: {"status": "production_ready", "remaining_gap": None})
    monkeypatch.setattr(main, "_role_product_surfaces_payload", lambda: {"status": "ready"})
    monkeypatch.setattr(main, "_deep_memory_graph_payload", lambda limit=80: {"status": "ready"})
    monkeypatch.setattr(main, "_decision_traces_payload", lambda limit=12: {"status": "ready", "coverage": {"action_records": 1}})
    async def fake_promotion_governance():
        return promotion

    monkeypatch.setattr(main, "_promotion_governance_payload", fake_promotion_governance)
    platform = run(main._platform_maturity_payload())
    assert platform["status"] == "ready"
    assert {row["id"] for row in platform["dimensions"]} >= {"identity", "promotion_governance"}

    assert main._call_actual_training_status(lambda min_rows, run_gcp_training, detail=None: {"detail": detail}, 3, False, detail="full")["detail"] == "full"

    def old_signature(min_rows, run_gcp_training):
        return {"old": min_rows}

    assert main._call_actual_training_status(old_signature, 5, True, detail="x")["old"] == 5

    def bad_signature(min_rows, run_gcp_training, detail=None):
        raise TypeError("other failure")

    try:
        main._call_actual_training_status(bad_signature, 5, True, detail="x")
    except TypeError as error:
        assert "other failure" in str(error)
    else:
        raise AssertionError("expected TypeError")


def test_main_hot_path_env_mongo_body_and_auth_helpers(monkeypatch):
    monkeypatch.setenv("BAD_FLOAT", "not-a-float")
    monkeypatch.setenv("BAD_INT", "not-an-int")
    assert main._float_env("BAD_FLOAT", 2.5) == 2.5
    assert main._int_env("BAD_INT", 7) == 7
    assert main._timeout_tiers()["hot_path_seconds"] >= 0
    assert main._api_capability_registry()["entrypoint"] == "lazy-main"

    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DIRECT_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_MONGO_OPTIONAL", "true")
    assert main._hot_mongo_status()["ready"] is True

    monkeypatch.setenv("MONGODB_URI", "mongodb://unit")
    monkeypatch.setenv("PARKPULSE_READINESS_PING_MONGO", "false")
    configured = main._hot_mongo_status()
    assert configured["mode"] == "hot_path_configured_without_ping"
    assert configured["ready"] is True

    monkeypatch.setenv("PARKPULSE_READINESS_PING_MONGO", "true")
    main._mongo_hot_status_cache = None

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.admin = types.SimpleNamespace(command=lambda name: {"ok": name})

        def close(self):
            self.closed = True

    monkeypatch.setitem(sys.modules, "certifi", types.SimpleNamespace(where=lambda: "/tmp/ca.pem"))
    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=Client))
    assert main._hot_mongo_status()["connected"] is True

    main._mongo_hot_status_cache = None

    class BrokenClient:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("mongo refused")

    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=BrokenClient))
    failed = main._hot_mongo_status()
    assert failed["connected"] is False
    assert "mongo refused" in failed["readiness_issues"][0]

    sent = []

    async def send(message):
        sent.append(message)

    run(main._send_json(send, 202, {"ok": True}))
    assert sent[0]["status"] == 202
    assert json.loads(sent[1]["body"].decode()) == {"ok": True}

    events = iter(
        [
            {"type": "http.request", "body": b'{"a"', "more_body": True},
            {"type": "http.request", "body": b":1}", "more_body": False},
        ]
    )

    async def receive():
        return next(events)

    assert run(main._read_json_body(receive)) == {"a": 1}

    async def bad_receive():
        return {"type": "http.request", "body": b"[1]", "more_body": False}

    assert run(main._read_json_body(bad_receive)) == {}

    bounded = run(
        main._bounded_actual_training_readiness(
            lambda min_rows, run_gcp_training, detail=None: (_ for _ in ()).throw(RuntimeError("training slow")),
            10,
            timeout_env="BAD_FLOAT",
            default_timeout=1,
        )
    )
    assert bounded["status"] == "not_ready"
    assert bounded["debug"]["fallback"] == "actual_training_readiness_timeout"

    decisions = []

    async def auth_send(message):
        sent.append(message)

    monkeypatch.setenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", "true")
    monkeypatch.setattr(main, "verify_external_role_identity", lambda headers, default_role="ops_team": {"status": "missing", "authenticated": False})
    monkeypatch.setattr(main, "_write_jsonl_event", lambda path, event: decisions.append(event))
    decision = run(main._authorize_or_send(auth_send, {"method": "POST", "path": "/x", "headers": []}, "manage_learning", "model"))
    assert decision is None
    assert decisions[-1]["allowed"] is False


def test_parkpulse_api_role_tracer_origin_and_auth_helpers(monkeypatch):
    import parkpulse_api

    class Span:
        def set_attribute(self, *_args, **_kwargs):
            return None

    assert parkpulse_api._NoopSpan().set_attribute("k", "v") is None
    with parkpulse_api._NoopTracer().start_as_current_span("unit") as span:
        assert isinstance(span, parkpulse_api._NoopSpan)

    monkeypatch.delenv("PARKPULSE_ENABLE_OTEL_SPANS", raising=False)
    assert isinstance(parkpulse_api._get_tracer("unit"), parkpulse_api._NoopTracer)

    fake_tracer = object()
    fake_trace = types.SimpleNamespace(get_tracer=lambda name: fake_tracer)
    monkeypatch.setenv("PARKPULSE_ENABLE_OTEL_SPANS", "true")
    monkeypatch.setitem(sys.modules, "opentelemetry", types.SimpleNamespace(trace=fake_trace))
    assert parkpulse_api._get_tracer("unit") is fake_tracer
    monkeypatch.setitem(sys.modules, "opentelemetry", types.SimpleNamespace())
    assert isinstance(parkpulse_api._get_tracer("unit"), parkpulse_api._NoopTracer)

    monkeypatch.setenv("BAD_API_FLOAT", "bad")
    assert parkpulse_api._float_env("BAD_API_FLOAT", 4.5) == 4.5
    assert parkpulse_api._truthy(None, True) is True
    assert parkpulse_api._truthy("on") is True

    monkeypatch.setenv("PARKPULSE_ALLOWED_ORIGINS", "https://a.test, https://b.test")
    monkeypatch.setenv("PARKPULSE_STRICT_ALLOWED_ORIGINS", "true")
    assert parkpulse_api._allowed_origins() == ["https://a.test", "https://b.test"]
    monkeypatch.setenv("PARKPULSE_STRICT_ALLOWED_ORIGINS", "false")
    assert "http://localhost:3000" in parkpulse_api._allowed_origins()

    monkeypatch.setenv("PARKPULSE_ENABLE_DEV_ROLE_ISSUER", "false")
    assert parkpulse_api._dev_role_issuer_enabled() is False
    monkeypatch.delenv("PARKPULSE_ENABLE_DEV_ROLE_ISSUER", raising=False)
    monkeypatch.setenv("PARKPULSE_ENV", "production")
    assert parkpulse_api._dev_role_issuer_enabled() is False
    monkeypatch.setenv("PARKPULSE_ENV", "local")
    monkeypatch.setattr(parkpulse_api, "identity_provider_readiness", lambda: {"external_identity_ready": True})
    assert parkpulse_api._dev_role_issuer_enabled() is False
    monkeypatch.setattr(parkpulse_api, "identity_provider_readiness", lambda: {"external_identity_ready": False})
    assert parkpulse_api._dev_role_issuer_enabled() is True

    monkeypatch.setenv("PARKPULSE_ROLE_SESSION_TTL_SECONDS", "bad")
    assert parkpulse_api._role_session_ttl_seconds() == 3600
    monkeypatch.setenv("PARKPULSE_ROLE_SESSION_TTL_SECONDS", "1")
    assert parkpulse_api._role_session_ttl_seconds() == 300

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    def request(headers: list[tuple[bytes, bytes]]):
        return parkpulse_api.Request({"type": "http", "method": "POST", "path": "/unit", "headers": headers}, receive)

    assert parkpulse_api._extract_role_token(request([(b"x-parkpulse-role-token", b"explicit")])) == "explicit"
    assert parkpulse_api._extract_role_token(request([(b"authorization", b"Bearer bearer-token")])) == "bearer-token"
    assert parkpulse_api._extract_role_token(request([])) is None

    monkeypatch.setattr(
        parkpulse_api,
        "verify_external_role_identity",
        lambda headers, default_role="ops_team": {"status": "role_unmapped", "authenticated": False, "role": "guest"},
    )
    assert parkpulse_api._request_role_context(request([]))["status"] == "role_unmapped"

    monkeypatch.setattr(parkpulse_api, "verify_external_role_identity", lambda headers, default_role="ops_team": {"status": "missing", "authenticated": False})
    monkeypatch.setenv("PARKPULSE_ROLE_AUTH_SECRET", "api-secret")
    token = parkpulse_api.sign_role_session("subject", "ml_ops_admin", parkpulse_api._role_auth_secret(), ttl_seconds=300)
    signed = parkpulse_api._request_role_context(request([(b"authorization", f"Bearer {token}".encode())]))
    assert signed["auth_method"] == "signed_role_session"

    monkeypatch.setenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", "true")
    required = parkpulse_api._request_role_context(request([]), {"role": "customer"})
    assert required["status"] == "unauthenticated"

    monkeypatch.setenv("PARKPULSE_ROLE_AUTH_SECRET", "prod-secret")
    monkeypatch.setattr(parkpulse_api, "identity_provider_readiness", lambda: {"external_identity_ready": True, "external_identity_providers": {"iap": True}})
    assert parkpulse_api._identity_readiness_payload()["status"] == "production_ready"

    monkeypatch.setattr(parkpulse_api, "_request_role_context", lambda req, payload=None, default="ops_team": {"authenticated": True, "role": "ops_team"})
    monkeypatch.setattr(parkpulse_api, "authorize_role_action", lambda *args, **kwargs: {"status": "allowed", "allowed": True})
    assert parkpulse_api._require_role_action(request([]), "read_ops_evidence", "dashboard")["allowed"] is True

    monkeypatch.setattr(parkpulse_api, "_request_role_context", lambda req, payload=None, default="ops_team": {"authenticated": False, "role": "ops_team", "reason": "token missing"})
    monkeypatch.setattr(parkpulse_api, "authorize_role_action", lambda *args, **kwargs: {"status": "forbidden", "allowed": True})
    with pytest.raises(parkpulse_api.HTTPException) as error:
        parkpulse_api._require_role_action(request([]), "manage_learning", "model")
    assert error.value.status_code == 401


def _dispatch(channel: str, payload: dict, response: dict):
    return {"id": f"{channel}-1", "channel": channel, "payload": payload, "response": response, "status": "observed"}


def test_park_simulation_closed_loop_outcome_domains():
    cases = [
        (
            "food",
            "react_role_food_spike mobile order food court",
            [_dispatch("guest_app", {"message": "Food Court A mobile order pickup redirect", "role": "menu_control"}, {"followThroughCount": 180, "acceptedCount": 180})],
        ),
        (
            "ride",
            "Dragon Coaster queue intake reroute",
            [_dispatch("guest_app", {"message": "Dragon Coaster ride queue reroute"}, {"followThroughCount": 220, "acceptedCount": 220})],
        ),
        (
            "staff",
            "react_role_staff_shortage understaffed",
            [_dispatch("worker_device", {"role": "crowd_control", "message": "staff break support"}, {"acknowledgedCount": 4})],
        ),
        (
            "medical",
            "medical team first aid fainted guest",
            [_dispatch("worker_device", {"role": "medical", "message": "medical team first aid"}, {"acknowledgedCount": 2})],
        ),
        (
            "crowd",
            "panic crowd safety calm route security",
            [_dispatch("guest_app", {"message": "calm route security crowd congestion"}, {"followThroughCount": 100, "acceptedCount": 100})],
        ),
        (
            "energy",
            "hvac equipment_controller setpoint comfort",
            [_dispatch("equipment_controller", {"command": "hvac setpoint comfort"}, {"applied": True})],
        ),
    ]

    for expected_domain, reason, dispatches in cases:
        sim = ParkSimulation()
        result = run(sim.apply_delivery_outcomes(dispatches, reason))
        assert result["status"] == "success"
        assert result["stateImpact"]["domain"] == expected_domain
        assert result["episode_fitness"]["source"] == "closed_loop_dispatch_outcome"


def test_park_simulation_time_replay_noop_and_events():
    sim = ParkSimulation()
    state = run(sim.set_time(99, -5))
    assert state["simTime"]["hour"] == 23
    assert state["simTime"]["minute"] == 0

    replay = run(sim.start_replay_run(seed="unit", scenario_key="bad_scenario"))
    assert replay["status"] == "success"
    assert replay["run"]["scenario_key"] == "ride_down"

    noop = run(sim.execute_action("unknown", "noop"))
    assert noop["status"] == "noop"
    event = run(sim.inject_event("unknown", "gardenLoop", 150))
    assert event["event"]["intensity"] == 100
    fitness = run(sim.get_episode_fitness(limit=2))
    assert fitness["mode"].startswith("live_episode_fitness")
