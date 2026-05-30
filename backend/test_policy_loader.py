import json

import policy_loader
from synthetic_park_knowledge import retrieve_synthetic_park_context, synthetic_coverage_report


def test_get_policy_books_loads_legacy_and_directory_books(tmp_path, monkeypatch):
    legacy = tmp_path / "policy_book.json"
    policy_dir = tmp_path / "policy_books"
    policy_dir.mkdir()
    legacy.write_text(json.dumps({"name": "legacy"}), encoding="utf-8")
    (policy_dir / "zeta.json").write_text(json.dumps({"name": "zeta"}), encoding="utf-8")
    (policy_dir / "alpha.json").write_text(json.dumps({"name": "alpha"}), encoding="utf-8")
    (policy_dir / "ignored.txt").write_text("not json", encoding="utf-8")

    monkeypatch.setattr(policy_loader, "LEGACY_POLICY_BOOK", legacy)
    monkeypatch.setattr(policy_loader, "POLICY_BOOK_DIR", policy_dir)

    result = policy_loader.get_policy_books()

    assert result["policy_book_count"] == 3
    assert [book["source"] for book in result["policy_books"]] == [
        "policy_book.json",
        "policy_books/alpha.json",
        "policy_books/zeta.json",
    ]
    assert result["policy_books"][1]["content"] == {"name": "alpha"}


def test_get_policy_books_handles_missing_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(policy_loader, "LEGACY_POLICY_BOOK", tmp_path / "missing.json")
    monkeypatch.setattr(policy_loader, "POLICY_BOOK_DIR", tmp_path / "missing_policy_books")

    assert policy_loader.get_policy_books() == {
        "policy_book_count": 0,
        "policy_books": [],
    }


def test_load_policy_books_text_returns_json(monkeypatch):
    monkeypatch.setattr(
        policy_loader,
        "get_policy_books",
        lambda: {"policy_book_count": 1, "policy_books": [{"source": "demo", "content": {"rule": "keep aggregate"}}]},
    )

    text = policy_loader.load_policy_books_text()

    assert '"policy_book_count": 1' in text
    assert '"keep aggregate"' in text


def test_load_policy_books_text_reports_loader_error(monkeypatch):
    def raise_error():
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(policy_loader, "get_policy_books", raise_error)

    assert policy_loader.load_policy_books_text() == "Policy books unavailable: disk unavailable"


def test_actual_policy_books_are_clean_parkpulse_books():
    result = policy_loader.get_policy_books()
    validation = policy_loader.validate_policy_books(result)
    reference_index = policy_loader.policy_reference_index(result)

    assert validation["status"] == "clean"
    assert validation["stale_terms"] == []
    assert validation["missing_active_books"] == []
    assert validation["missing_required_refs"] == []
    assert "parkpulse_governance_index" in validation["book_ids"]
    assert "parkpulse_operations_policy_book" in validation["book_ids"]
    assert "actionable_agent_policy_book" in validation["book_ids"]
    assert "researched_scenario_case_study_policy_book" in validation["book_ids"]
    assert "ride_safety_policy_book" in validation["book_ids"]
    assert "labor_stress_policy_book" in validation["book_ids"]
    assert "guest_privacy_policy_book" in validation["book_ids"]
    assert "eventops_planning_policy_book" in validation["book_ids"]
    assert "equipment_control_policy_book" in validation["book_ids"]
    assert "gcp_internal_eval_policy_book" in validation["book_ids"]
    assert "PARK-SAFE-001" in reference_index["policy_refs"]
    assert "PARK-OPS-001" in reference_index["policy_refs"]
    assert "PARK-EXP-001" in reference_index["policy_refs"]
    assert "PARK-CARE-001" in reference_index["policy_refs"]
    assert "PARK-LABOR-002" in reference_index["policy_refs"]
    assert "PARK-MSG-003" in reference_index["policy_refs"]
    assert "PARK-ACT-001" in reference_index["policy_refs"]


def test_operational_doctrine_has_broad_researched_case_coverage():
    index = policy_loader.operational_doctrine_index()
    case_ids = {case["id"] for case in index["action_cases"]}

    assert index["action_case_count"] >= 45
    assert "CASE-RIDE-EVAC-001" in case_ids
    assert "CASE-CROWD-CRUSH-PINCHPOINT-001" in case_ids
    assert "CASE-WATERPARK-LIFEGUARD-RESCUE-001" in case_ids
    assert "CASE-POWER-OUTAGE-RIDES-001" in case_ids
    assert "CASE-PRIVACY-PII-IN-OPERATOR-TEXT-001" in case_ids


def test_synthetic_park_knowledge_has_broad_conversational_coverage():
    coverage = synthetic_coverage_report()

    assert coverage["object_count"] >= 5
    assert coverage["example_count"] >= 12
    assert coverage["utterance_count"] >= 55
    assert coverage["domain_count"] >= 9
    assert "guest_care_security" in coverage["domains"]
    assert "ride_safety" in coverage["domains"]
    assert "map_question" in coverage["domains"]
    assert "CASE-LOST-CHILD-FOODCOURT-001" in coverage["expected_case_ids"]


def test_synthetic_park_context_retrieves_map_facts_and_expected_agent_owner():
    context = retrieve_synthetic_park_context("how far is the coaster from the front gate", {})

    assert context["retrieval_status"] == "matched"
    assert context["primary_example"]["id"] == "SYN-MAP-DISTANCE-001"
    facts = " ".join(fact for obj in context["matched_objects"] for fact in obj.get("facts", []))
    assert "677 meters" in facts
    assert any(obj["id"] == "dragonCoaster" for obj in context["matched_objects"])


def test_operational_doctrine_includes_synthetic_context_for_incidents():
    doctrine = policy_loader.retrieve_operational_doctrine("missing kid at the foodcourt", {})
    synthetic = doctrine["synthetic_context"]

    assert doctrine["primary_case"]["id"] == "CASE-LOST-CHILD-FOODCOURT-001"
    assert synthetic["primary_example"]["id"] == "SYN-LOST-CHILD-001"
    assert synthetic["primary_example"]["expected_owner"] == "Guest Care + Security Agent"
    assert "safety_over_food" in synthetic["primary_example"]["evaluation_assertions"]


def test_researched_scenario_retrieval_matches_edge_cases():
    examples = [
        ("guests are stuck on ride and need ride evacuation", "CASE-RIDE-EVAC-001"),
        ("unattended bag found near the queue", "CASE-SECURITY-UNATTENDED-BAG-001"),
        ("lifeguard rescue in the wave pool", "CASE-WATERPARK-LIFEGUARD-RESCUE-001"),
        ("partial power outage and lights out near rides", "CASE-POWER-OUTAGE-RIDES-001"),
        ("operator text contains phone number and guest name pii", "CASE-PRIVACY-PII-IN-OPERATOR-TEXT-001"),
    ]

    for message, expected_case in examples:
        result = policy_loader.retrieve_operational_doctrine(message, {})
        assert result["primary_case"]["id"] == expected_case


def test_semantic_retrieval_handles_non_exact_language():
    examples = [
        ("child separated from parents near restaurant", "CASE-LOST-CHILD-FOODCOURT-001"),
        ("blackout around coaster and no power in that area", "CASE-POWER-OUTAGE-RIDES-001"),
        ("someone collapsed and cannot breathe by the queue", "CASE-MEDICAL-CHEST-PAIN-001"),
        ("backpack left unclaimed near coaster line", "CASE-SECURITY-UNATTENDED-BAG-001"),
    ]

    for message, expected_case in examples:
        result = policy_loader.retrieve_operational_doctrine(message, {})
        assert result["primary_case"]["id"] == expected_case


def test_policy_interpretation_prioritizes_high_risk_conflicts():
    message = "child separated near restaurant while food orders are backed up and coaster queue is long"
    doctrine = policy_loader.retrieve_operational_doctrine(message, {})
    reasoning = policy_loader.interpret_policy_for_action(message, {}, doctrine)

    assert reasoning["primary_case_id"] == "CASE-LOST-CHILD-FOODCOURT-001"
    assert reasoning["conflict_analysis"]["detected"] is True
    assert reasoning["conflict_analysis"]["priority_order"][0]["case_id"] == "CASE-LOST-CHILD-FOODCOURT-001"


def test_retrieve_operational_doctrine_selects_action_case():
    result = policy_loader.retrieve_operational_doctrine(
        "The coaster queue is too long and families are stuck near the parade. What should we do?",
        {
            "top_zones": [{"id": "coasterPlaza", "name": "Coaster Plaza", "density": 91}],
            "constrained_rides": [{"id": "dragonCoaster", "name": "Dragon Coaster", "status": "down"}],
        },
    )

    assert result["retrieval_status"] == "matched"
    assert result["primary_case"]["id"] == "CASE-RIDE-DOWN-PARADE-001"
    assert "PARK-ACT-001" in result["policy_refs"]
    assert result["doctrine_index"]["action_case_count"] >= 6


def test_interpret_policy_for_action_builds_nine_step_reasoning():
    doctrine = policy_loader.retrieve_operational_doctrine(
        "The coaster queue is too long and families are stuck near the parade. What should we do?",
        {
            "top_zones": [{"id": "coasterPlaza", "name": "Coaster Plaza", "density": 91}],
            "constrained_rides": [{"id": "dragonCoaster", "name": "Dragon Coaster", "status": "down"}],
        },
    )

    reasoning = policy_loader.interpret_policy_for_action(
        "The coaster queue is too long and families are stuck near the parade. What should we do?",
        {
            "top_zones": [{"id": "coasterPlaza", "name": "Coaster Plaza", "density": 91}],
            "constrained_rides": [{"id": "dragonCoaster", "name": "Dragon Coaster", "status": "down"}],
        },
        doctrine,
    )

    assert reasoning["status"] == "interpreted"
    assert len(reasoning["steps"]) == 9
    assert reasoning["primary_case_id"] == "CASE-RIDE-DOWN-PARADE-001"
    assert reasoning["selected_action"]["verdict"] == "candidate"
    assert any("route all guests" in item.lower() for item in reasoning["blocked_actions"])


def test_validate_policy_books_rejects_bad_applies_to_shape():
    books = {
        "policy_books": [
            {
                "source": "bad",
                "content": {
                    "policy_book_id": "bad_policy_book",
                    "decision_rules": [
                        {
                            "id": "BAD-001",
                            "applies_to": {"targets": "ride", "unknown": ["x"]},
                        }
                    ],
                },
            }
        ]
    }

    validation = policy_loader.validate_policy_books(books)

    assert validation["status"] == "needs_cleanup"
    assert "BAD-001.applies_to.targets must be a list of strings" in validation["issues"]
    assert "BAD-001.applies_to has unknown keys: unknown" in validation["issues"]


def test_validate_policy_books_rejects_bad_condition_shape():
    books = {
        "policy_books": [
            {
                "source": "bad",
                "content": {
                    "policy_book_id": "bad_policy_book",
                    "decision_rules": [
                        {
                            "id": "BAD-002",
                            "block_conditions": [
                                {
                                    "targets": ["ride"],
                                    "state": {"bad_state": True, "any_zone_density_gte": "high"},
                                    "bad_key": "bad",
                                }
                            ],
                            "review_conditions": {"message": "bad"},
                        }
                    ],
                },
            }
        ]
    }

    validation = policy_loader.validate_policy_books(books)

    assert validation["status"] == "needs_cleanup"
    assert "BAD-002.block_conditions[0].message is required" in validation["issues"]
    assert "BAD-002.block_conditions[0] has unknown keys: bad_key" in validation["issues"]
    assert "BAD-002.block_conditions[0].state has unknown keys: bad_state" in validation["issues"]
    assert "BAD-002.block_conditions[0].state.any_zone_density_gte must be an integer" in validation["issues"]
    assert "BAD-002.review_conditions must be a list" in validation["issues"]


def test_validate_policy_books_rejects_missing_monitoring_lane_ref():
    books = {
        "policy_books": [
            {
                "source": "policy_book.json",
                "content": {
                    "policy_book_id": "parkpulse_governance_index",
                    "default_action_policy_refs": ["MISSING-DEFAULT"],
                    "monitoring_lanes": [{"area": "Safety", "primary_policy_ref": "MISSING-LANE"}],
                },
            },
            {
                "source": "rules",
                "content": {
                    "policy_book_id": "rules",
                    "decision_rules": [{"id": "KNOWN-001"}],
                },
            },
        ]
    }

    validation = policy_loader.validate_policy_books(books)

    assert validation["status"] == "needs_cleanup"
    assert "Default action policy ref is missing: MISSING-DEFAULT" in validation["issues"]
    assert "Monitoring lane primary_policy_ref is missing: MISSING-LANE" in validation["issues"]
