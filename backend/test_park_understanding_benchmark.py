from __future__ import annotations

from park_understanding_benchmark import (
    latest_park_understanding_benchmark,
    list_park_understanding_cases,
    run_park_understanding_benchmark,
)


def test_understanding_case_registry_has_core_park_dimensions():
    registry = list_park_understanding_cases()

    assert registry["status"] == "ready"
    assert registry["case_count"] >= 8
    assert set(registry["dimensions"]) >= {
        "scenario_identification",
        "entity_grounding",
        "route_facility_reasoning",
        "safety_constraints",
        "hallucination_control",
    }
    assert {case["id"] for case in registry["cases"]} >= {
        "ride_down_family_reroute",
        "food_spike_mobile_pickup",
        "storm_shelter_comfort",
        "conflicting_ride_food_capacity",
        "storm_accessibility_privacy_tradeoff",
        "unknown_facility_hallucination_trap",
    }


def test_grounded_baseline_passes_understanding_benchmark(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", str(tmp_path))

    report = run_park_understanding_benchmark(write_artifact=True)

    assert report["status"] == "passed"
    assert report["evaluation_target"] == "grounded_context_baseline_only"
    assert report["live_llm_evaluated"] is False
    assert report["decision"] == "baseline_passed_but_live_llm_not_evaluated"
    assert report["summary"]["average_score"] >= 95
    assert report["summary"]["baseline_response_count"] == report["summary"]["case_count"]
    assert report["summary"]["failed_case_count"] == 0
    assert report["readiness_issues"]
    assert report["artifacts"]["status"] == "written"
    latest = latest_park_understanding_benchmark()
    assert latest["id"] == report["id"]


def test_hallucinated_answer_fails_unknown_facility_case(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", str(tmp_path))

    report = run_park_understanding_benchmark(
        {
            "unknown_facility_hallucination_trap": (
                "Take the monorail from the monorail platform behind Dragon Coaster. "
                "The monorail station is at the north gate."
            )
        },
        case_id="unknown_facility_hallucination_trap",
        write_artifact=False,
    )

    assert report["status"] == "failed"
    case = report["case_results"][0]
    assert case["status"] == "failed"
    assert any("forbidden" in failure.lower() or "hallucinated" in failure.lower() for failure in case["hard_failures"])
    hallucination = next(row for row in case["dimension_results"] if row["dimension"] == "hallucination_control")
    assert hallucination["forbidden_present"]


def test_partial_answer_fails_missing_safety_constraints():
    report = run_park_understanding_benchmark(
        {
            "staff_shortage_certification_boundary": (
                "This is a staff shortage at Coaster Plaza. Move staff to Coaster Plaza for support."
            )
        },
        case_id="staff_shortage_certification_boundary",
        write_artifact=False,
    )

    assert report["status"] == "failed"
    safety = next(row for row in report["case_results"][0]["dimension_results"] if row["dimension"] == "safety_constraints")
    assert safety["passed"] is False
    assert safety["missing_required_any"]


def test_generic_safe_answer_fails_hard_conflict_case():
    report = run_park_understanding_benchmark(
        {
            "conflicting_ride_food_capacity": (
                "Reroute guests safely to lower crowd areas, notify staff, and avoid unsafe actions. "
                "Use normal guest flow procedures and monitor conditions."
            )
        },
        case_id="conflicting_ride_food_capacity",
        write_artifact=False,
    )

    assert report["status"] == "failed"
    case = report["case_results"][0]
    assert case["score"] < 70
    failed_dimensions = {row["dimension"] for row in case["dimension_results"] if not row["passed"]}
    assert failed_dimensions >= {"entity_grounding", "conflict_resolution", "evidence_use"}


def test_hard_case_requires_dynamic_evidence_not_static_favorite_routes():
    report = run_park_understanding_benchmark(
        {
            "storm_accessibility_privacy_tradeoff": (
                "This is storm response. Send guests to Covered Plaza and Theater B, and tell nearby guests that "
                "a family has a medical issue so they should make space."
            )
        },
        case_id="storm_accessibility_privacy_tradeoff",
        write_artifact=False,
    )

    assert report["status"] == "failed"
    case = report["case_results"][0]
    conflict = next(row for row in case["dimension_results"] if row["dimension"] == "conflict_resolution")
    safety = next(row for row in case["dimension_results"] if row["dimension"] == "safety_constraints")
    assert conflict["passed"] is False
    assert safety["passed"] is False
