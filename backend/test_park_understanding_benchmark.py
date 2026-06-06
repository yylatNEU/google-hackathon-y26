from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from park_understanding_benchmark import (
    _candidate_text,
    _generation_retry_reason,
    _norm,
    _operations_understanding_context,
    _parse_json_object,
    _repair_answer_object,
    _understanding_generation_prompt,
    build_grounded_baseline_answer,
    generate_live_park_understanding_responses,
    latest_park_understanding_benchmark,
    list_park_understanding_cases,
    run_park_understanding_benchmark,
    run_live_park_understanding_benchmark,
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


def test_understanding_parser_repair_and_retry_edges():
    assert _norm({"route_mix": ["Food-Court_B"]}) == '{"route mix": ["food court b"]}'
    assert _candidate_text({"scenario": "ride_down", "note": "Use Theater B", "message": "  "}) == "Use Theater B"
    assert _candidate_text(None) == ""
    assert _parse_json_object("") == {}
    assert _parse_json_object("[1, 2]") == {}
    assert _parse_json_object('prefix {"answer": "ok"} suffix') == {"answer": "ok"}
    assert _parse_json_object('prefix {"answer": } suffix') == {}
    assert _repair_answer_object('{"answer": "Scenario: ok"}') == {"answer": "Scenario: ok"}
    assert _repair_answer_object('"answer": "Line one\\nLine two"}') == {"answer": "Line one Line two"}
    assert _repair_answer_object("no marker") == {}
    assert _repair_answer_object('"answer" missing colon') == {}
    assert _generation_retry_reason("", {}) == "missing_answer"
    assert _generation_retry_reason('{"answer": ', {"answer": "bad json"}) == "malformed_json"
    assert _generation_retry_reason('{"answer": "short"}', {"answer": "short"}) == "incomplete_structured_answer"
    complete = (
        "Scenario: ride_down. Entities: Dragon Coaster and Theater B. Route: split guests to Theater B. "
        "Reject: do not reopen without clearance. Safety: crowd-control support and maintenance clearance. " * 3
    )
    assert _generation_retry_reason(json.dumps({"answer": complete}), {"answer": complete}) is None


def test_generation_prompt_and_baseline_boundaries_are_grounded():
    case = list_park_understanding_cases()["cases"][0]
    full_case = {
        **case,
        "expected_answer": {"answer": "Use known venues."},
    }
    answer = build_grounded_baseline_answer(full_case, {"version": "unit", "boundaries": ["a", "b", "c", "d"]})
    assert answer["known_venue_version"] == "unit"
    assert answer["boundaries"] == ["a", "b", "c"]

    context = _operations_understanding_context()
    assert "ride_down" in context["scenario_labels"]
    prompt = _understanding_generation_prompt(
        full_case,
        {
            "attractions": [{"id": "ride", "name": "Dragon", "zone_id": "z", "indoor": False, "outdoor": True, "family_fit": True}, "bad"],
            "food": [{"id": "food", "name": "Food Court B", "zone_id": "z", "mobile_order": True, "guest_tips": ["fast"]}, "bad"],
            "landmarks": {"front": "Front Gate"},
            "venue_map": {"nodes": [{"id": "n", "name": "Node", "type": "landmark", "zone_id": "z"}, "bad"]},
            "boundaries": ["no invented routes"],
        },
    )
    assert prompt["case"]["id"] == case["id"]
    assert prompt["known_park_facts"]["attractions"][0]["id"] == "ride"
    assert prompt["known_park_facts"]["food"][0]["guest_tips"] == ["fast"]
    assert prompt["known_park_facts"]["venue_map_nodes"][0]["name"] == "Node"


def test_understanding_benchmark_not_found_and_mixed_candidate_target():
    missing = run_park_understanding_benchmark(case_id="missing", write_artifact=False)
    assert missing["status"] == "not_found"
    assert missing["available"]

    case_id = list_park_understanding_cases()["cases"][0]["id"]
    report = run_park_understanding_benchmark(
        {
            case_id: (
                "Scenario: ride down at Dragon Coaster. Entities: Dragon Coaster, Coaster Plaza, Theater B, Arcade Zone, Food Court B. "
                "Route: split and reroute families toward Theater B, Arcade Zone, Covered Plaza, and Food Court B. "
                "Reject: do not reopen without maintenance clearance and avoid Food Court A overload. "
                "Safety: add crowd control staff for families."
            )
        },
        write_artifact=False,
    )
    assert report["evaluation_target"] == "mixed_candidate_and_baseline"
    assert report["summary"]["provided_response_count"] == 1
    assert report["live_llm_evaluated"] is False


def test_latest_understanding_report_empty_error_and_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", str(tmp_path / "missing"))
    assert latest_park_understanding_benchmark()["status"] == "empty"

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", str(empty_dir))
    assert latest_park_understanding_benchmark()["status"] == "empty"

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "bad.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", str(bad_dir))
    assert latest_park_understanding_benchmark()["status"] == "error"

    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    (invalid_dir / "invalid.json").write_text("[1, 2]", encoding="utf-8")
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", str(invalid_dir))
    assert latest_park_understanding_benchmark()["status"] == "invalid"


def test_live_understanding_generation_retry_failure_and_wrapper(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", str(tmp_path))
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_GEMINI_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("PARKPULSE_UNDERSTANDING_GEMINI_MAX_OUTPUT_TOKENS", "123")
    monkeypatch.setitem(sys.modules, "env_bootstrap", SimpleNamespace(load_backend_env=lambda: None))

    calls = []

    async def fake_generate(prompt, **kwargs):
        calls.append((prompt, kwargs))
        if len(calls) == 1:
            return {"text": '{"answer": "short"}', "transport": "unit", "finish_reason": "stop"}
        return {
            "text": json.dumps(
                {
                    "answer": (
                        "Scenario: ride_down. Entities: Dragon Coaster, Coaster Plaza, Theater B, Arcade Zone, Food Court B. "
                        "Route: split guests toward Theater B and Food Court B. Reject: do not reopen without maintenance clearance. "
                        "Safety: add crowd-control staff and avoid Food Court A overload. " * 2
                    )
                }
            ),
            "transport": "unit",
            "finish_reason": "stop",
            "usage_metadata": {"tokens": 10},
        }

    monkeypatch.setitem(sys.modules, "gemini_hard_timeout", SimpleNamespace(generate_gemini_json_hard_timeout=fake_generate))
    result = asyncio.run(generate_live_park_understanding_responses(case_id="ride_down_family_reroute"))
    assert result["status"] == "complete"
    assert result["generated_count"] == 1
    assert result["generations"][0]["retry_count"] == 1
    assert calls[1][0]["previous_generation_issue"] == "incomplete_structured_answer"
    assert calls[0][1]["timeout_seconds"] == 0.2
    assert calls[0][1]["max_output_tokens"] == 123

    async def failing_generate(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setitem(sys.modules, "gemini_hard_timeout", SimpleNamespace(generate_gemini_json_hard_timeout=failing_generate))
    failed = asyncio.run(generate_live_park_understanding_responses(case_id="ride_down_family_reroute", timeout_seconds=0.1, max_output_tokens=20))
    assert failed["status"] == "failed"
    assert failed["generations"][0]["status"] == "failed"

    missing = asyncio.run(run_live_park_understanding_benchmark(case_id="missing"))
    assert missing["status"] == "not_found"

    monkeypatch.setitem(sys.modules, "gemini_hard_timeout", SimpleNamespace(generate_gemini_json_hard_timeout=fake_generate))
    calls.clear()
    report = asyncio.run(run_live_park_understanding_benchmark(case_id="ride_down_family_reroute", write_artifact=False))
    assert report["provider"] == "gemini"
    assert report["evaluation_target"] == "live_gemini_responses"
    assert report["generation"]["status"] == "complete"
