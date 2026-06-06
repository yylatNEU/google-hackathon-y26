import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")
os.environ.setdefault("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "false")

import pytest

import main
import agent_ops_ledger
import controlled_training_generation
import digital_twin_tools
import gemini_hard_timeout
import incident_analytics
import park_actual_training
import park_audit_agent
import park_delivery
import park_signal_intake
import park_simulation
import parkpulse_api
import review_label_pipeline
import training_readiness


def run(coro):
    return asyncio.run(coro)


def compact_state():
    return {
        "product": {"name": "Unit Test Park"},
        "simTime": {"label": "15:00"},
        "guestFlow": {
            "representedGuests": 1800,
            "avgSatisfaction": 72,
            "activePolicy": "bounded",
            "activeScenario": {"name": "Parade pressure"},
            "rides": [
                {
                    "id": "dragonCoaster",
                    "name": "Dragon Coaster",
                    "zone": "coasterPlaza",
                    "zoneName": "Coaster Plaza",
                    "waitMins": 72,
                    "queueGuests": 420,
                    "status": "constrained",
                    "downtimeRisk": 61,
                    "staffAvailable": 3,
                    "staffRequired": 4,
                    "effectiveThroughput": 610,
                    "capacityPerHour": 780,
                },
                {
                    "id": "theaterB",
                    "name": "Theater B",
                    "zone": "indoorHub",
                    "zoneName": "Indoor Hub",
                    "waitMins": 8,
                    "queueGuests": 40,
                    "status": "normal",
                    "downtimeRisk": 5,
                },
            ],
            "zones": [
                {"id": "foodCourt1", "name": "Food Court A", "area": "east", "density": 91, "waitMins": 18, "comfortScore": 44},
                {"id": "indoorHub", "name": "Indoor Hub", "area": "north", "density": 38, "waitMins": 4, "comfortScore": 83},
            ],
            "paths": [
                {
                    "id": "path-food-indoor",
                    "from": "foodCourt1",
                    "to": "indoorHub",
                    "fromName": "Food Court A",
                    "toName": "Indoor Hub",
                    "walkMinutes": 6,
                    "congestionLevel": 82,
                    "status": "congested",
                }
            ],
        },
        "weather": {"condition": "hot", "temperatureF": 91, "heatIndexF": 98, "stormRisk": 12},
        "staffing": {"checkedIn": 96, "openCallouts": 4},
        "parkOps": {"mode": "live", "staffReadyPct": 86},
        "foodInventory": {
            "mode": "mobile_order_pressure",
            "risk": "medium",
            "lowStockItems": ["water"],
            "locations": [
                {
                    "id": "foodCourt1",
                    "name": "Food Court A",
                    "pickupEtaMinutes": 22,
                    "mobileOrderBacklog": 45,
                    "lowInventoryItems": ["water"],
                    "availableItems": ["pizza", "pretzel"],
                },
                {"id": "foodCourtB", "name": "Food Court B", "pickupEtaMinutes": 5, "mobileOrderBacklog": 3},
            ],
        },
        "physicalMap": {
            "scale": {"widthMeters": 820, "heightMeters": 540, "north": "top"},
            "landmarks": [
                {"id": "frontGate", "name": "Front Gate", "type": "entry", "guestVisible": True, "x": 120, "y": 520, "w": 160, "h": 50},
                {"id": "backstage", "name": "Backstage", "type": "maintenance", "guestVisible": False, "x": 1, "y": 1},
            ],
            "facilities": [{"id": "waterNorth", "name": "Water", "type": "water", "x": 500, "y": 200}],
            "queues": [{"id": "q-dragon", "name": "Dragon Queue", "rideId": "dragonCoaster", "waitMins": 72, "status": "open"}],
            "serviceRoutes": [{"id": "er-1", "access": "emergency", "blocked": True}],
        },
        "operatingClock": {
            "eventSchedule": {
                "eventTrafficRiskPct": 76,
                "nextEvent": {"id": "parade", "name": "Parade", "kind": "show", "trafficRiskPct": 82},
                "activeEvents": [{"id": "show", "name": "Show", "trafficRiskPct": 65}],
                "showtimes": [{"id": "show2", "name": "Show 2", "minutesUntilStart": 25, "trafficRiskPct": 20}],
            },
            "accessFairness": {"publicComplaintRiskPct": 48, "status": "watch"},
        },
        "guestCare": {
            "openCases": 42,
            "complaintRatePct": 19,
            "topDrivers": ["wait"],
            "recoveryQueue": [{"segment": "families", "safeAction": "offer indoor route"}],
        },
        "incidentReadiness": {"accessibilityRoutesOpen": False, "emergencyAccessBlocked": True},
        "alerts": [
            {"severity": "info", "title": "Parade route update", "detail": "Use Indoor Hub path."},
            {"severity": "internal", "title": "Staff policy update", "detail": "hidden"},
        ],
        "liveFeedEvidence": {"weather": {"trusted": True, "status": "fresh", "age_seconds": 5}},
    }


class FakeParkSimulation:
    async def get_state(self):
        return compact_state()

    async def get_state_lite(self):
        return compact_state()


def test_api_customer_training_and_threshold_helpers(monkeypatch):
    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation())
    monkeypatch.setattr(parkpulse_api, "_require_role_action", lambda *args, **kwargs: {"allowed": True})
    monkeypatch.setattr(parkpulse_api, "review_training_ledger", lambda limit=120: {"summary": {"training_candidate_count": 3}, "items": []})
    monkeypatch.setattr(parkpulse_api, "live_feed_health", lambda state, limit=120: {"summary": {"ready_feed_count": 5}, "rows": []})
    monkeypatch.setattr(review_label_pipeline, "review_label_decision_ledger", lambda limit=1000: {"summary": {"approved_label_count": 2}})
    monkeypatch.setattr(park_actual_training, "actual_training_status", lambda min_rows, include_rows, detail=None: {"status": "ready", "sample_count": min_rows})
    monkeypatch.setattr(
        training_readiness,
        "build_training_readiness_report",
        lambda **kwargs: {
            "status": "ready",
            "min_review_labels": kwargs["min_review_labels"],
            "min_outcome_rows": kwargs["min_outcome_rows"],
            "training_candidate_count": kwargs["review_ledger"]["summary"]["training_candidate_count"],
            "actual_status": kwargs["actual_training"]["status"],
        },
    )

    details = parkpulse_api._customer_public_park_details_for_api(compact_state())
    assert details["status"] == "ready"
    assert details["park"]["name"] == "Unit Test Park"
    assert details["rides"][0]["status"] == "high demand"
    assert details["zones"][0]["status"] == "high demand"
    assert details["routes"][0]["status"] == "congested"
    assert details["recommended_public_options"]["best_food"]["name"] == "Food Court A"
    assert details["customer_boundaries"]

    readiness = run(parkpulse_api.park_training_readiness(object(), minReviewLabels=4, minOutcomeRows=7))
    assert readiness == {
        "status": "ready",
        "min_review_labels": 4,
        "min_outcome_rows": 7,
        "training_candidate_count": 5,
        "actual_status": "ready",
    }

    monkeypatch.setenv("PARKPULSE_AUTO_LABEL_CONFIDENCE_THRESHOLD", "9")
    assert parkpulse_api._live_feed_auto_label_threshold_for_api() == 1.0
    monkeypatch.setenv("PARKPULSE_AUTO_LABEL_CONFIDENCE_THRESHOLD", "-1")
    assert parkpulse_api._live_feed_auto_label_threshold_for_api() == 0.0
    assert parkpulse_api._api_issue_text(TimeoutError("too slow"), "fallback") == "fallback"
    assert parkpulse_api._api_issue_text(RuntimeError("x" * 300), "fallback") == "x" * 240


def test_api_training_readiness_error_and_review_label_fallback(monkeypatch):
    def broken_status(*args, **kwargs):
        raise RuntimeError("training store unavailable")

    result = run(
        parkpulse_api._bounded_actual_training_readiness_for_api(
            broken_status,
            10,
            timeout_env="PARKPULSE_UNIT_TRAINING_TIMEOUT",
            default_timeout=1.0,
        )
    )
    assert result["status"] == "not_ready"
    assert result["debug"]["readiness_issues"][0] == "training store unavailable"

    monkeypatch.setattr(review_label_pipeline, "review_label_decision_ledger", lambda limit=1000: (_ for _ in ()).throw(RuntimeError("offline")))
    enriched = parkpulse_api._review_ledger_with_label_decisions_for_api({"summary": {"training_candidate_count": 6}})
    assert enriched["summary"]["approved_review_label_count"] == 0
    assert enriched["summary"]["training_candidate_count"] == 6
    assert enriched["review_label_decision_ledger"] == {}


def test_api_role_tool_trace_and_react_payload_branches(monkeypatch):
    monkeypatch.setattr(parkpulse_api, "evaluate_agent_role_trace", lambda route, trace: {"status": "pass", "tool_count": trace["tool_count"]})
    monkeypatch.setattr(parkpulse_api, "get_gemini_agent_properties", lambda: SimpleNamespace(ready=False))
    route = {
        "selected_role": "react",
        "skill": "parkpulse-react-agent",
        "policy_gates": ["bounded authority"],
        "expected_receipt": ["dispatch idempotency"],
        "required_tools": [
            "get_park_state",
            "get_noisy_observation",
            "get_weather",
            "retrieve_similar_incidents",
            "compare_action_candidates",
            "simulate_action",
            "tick_simulation",
            "validate_policy",
            "dispatch_worker_task",
            "score_outcome",
            "write_decision_memory",
            "inspect_runtime_status",
            "inspect_delivery_receipts",
            "inspect_observability_contract",
            "score_decision_quality",
            "explain_route",
        ],
    }

    trace = parkpulse_api._agent_role_tool_trace_for_api(route)
    capabilities = {call["tool"]: call["capability"] for call in trace["tool_calls"]}
    assert capabilities["get_park_state"] == "read"
    assert capabilities["validate_policy"] == "gate"
    assert capabilities["dispatch_worker_task"] == "act"
    assert capabilities["simulate_action"] == "simulate"
    assert capabilities["write_decision_memory"] == "memory"
    assert trace["deliberate_eval"]["status"] == "pass"

    assert parkpulse_api._agent_role_tool_output_for_api("dispatch_guest_message", route)["status"] == "prepared"
    assert parkpulse_api._agent_role_tool_output_for_api("score_decision_quality", route)["overall"] == 0.9

    food = parkpulse_api._fast_role_react_payload_for_api("food court mobile order backlog", route, trace)
    equipment = parkpulse_api._fast_role_react_payload_for_api("fog machine controller smoke", route, trace)
    care = parkpulse_api._fast_role_react_payload_for_api("medical guest faint at access lane", route, trace)
    custom = parkpulse_api._fast_role_react_payload_for_api("unusual crowd note", route, trace)
    assert food["operator_response"]["headline"].startswith("React Agent is rerouting food")
    assert equipment["operator_response"]["headline"].startswith("React Agent is holding")
    assert care["operator_response"]["headline"].startswith("React Agent is protecting")
    assert custom["operator_response"]["headline"].startswith("React Agent is executing")
    assert all(payload["role_run"]["dispatch_count"] == 3 for payload in (food, equipment, care, custom))


def test_api_copilot_read_only_and_object_reasoning(monkeypatch):
    state = compact_state()
    compact = parkpulse_api._compact_copilot_state(state)
    monkeypatch.setattr(
        parkpulse_api,
        "retrieve_synthetic_park_context",
        lambda *args, **kwargs: {
            "retrieval_status": "complete",
            "primary_example": {"id": "SYN-UNIT"},
            "matched_objects": [{"facts": ["synthetic queue fact", "synthetic policy fact"]}],
        },
    )

    assert parkpulse_api._copilot_data_request_kind("where is food court") == "map_location_food_court"
    assert parkpulse_api._copilot_data_request_kind("food report please") == "food_report"
    assert parkpulse_api._copilot_data_request_kind("medical fainting at first aid") is None
    assert "Food operations status" in parkpulse_api._copilot_data_answer("food_report", compact)["answer"]
    assert parkpulse_api._copilot_data_answer("ride_queues", {"all_ride_queues": []})["facts"] == []
    assert parkpulse_api._copilot_data_answer("map_location_food_court", compact)["facts"][0].startswith("Food Court A center")
    assert parkpulse_api._copilot_data_answer(None, compact) is None

    response = parkpulse_api._copilot_read_only_response(
        raw_message="food report please",
        recent_messages=[],
        request=parkpulse_api.CopilotChatRequest(message="food report please", selected_map_context={"source": "unit"}),
        compact_state=compact,
        route={"selected_role": "scan"},
        intent={"data_request_kind": "food_report", "is_question": True, "safety_sensitive": False},
        chat_brain={"source": "unit", "confidence": 10},
        data_answer=parkpulse_api._copilot_data_answer("food_report", compact),
    )
    assert response["mode"] == "answer"
    assert response["recommended_action"]["gate"] == "read_only"
    assert response["chat_brain"]["confidence"] == 90
    assert response["tool_trace"]["tool_calls"][1]["output"] == "SYN-UNIT"

    objects = [
        {
            "object_type": "SafetyReadiness",
            "id": "incident_readiness",
            "name": "Incident Readiness",
            "status": "watch",
            "permission": "supervisor_required",
            "allowed_actions": ["protect_access_lane", "dispatch_medical", "inspect"],
        },
        {
            "object_type": "StaffPool",
            "id": "staffing",
            "name": "Staffing",
            "status": "short",
            "permission": "supervisor_required",
            "allowed_actions": ["draft_redeploy_plan", "request_manager_approval", "inspect"],
        },
        {
            "object_type": "Zone",
            "id": "foodCourt1",
            "name": "Food Court A",
            "status": "busy",
            "allowed_actions": ["open_route", "send_crowd_lead", "inspect"],
        },
        {"object_type": "Ride", "id": "dragonCoaster", "name": "Dragon Coaster", "status": "down", "allowed_actions": ["inspect"]},
    ]
    plan = parkpulse_api._copilot_object_action_plan(
        "medical access lane issue, protect staff but avoid food court",
        objects,
        operator_approved=False,
        will_act=False,
    )
    assert plan["overall_gate"] == "approval_required"
    assert all("food" not in str(action["object_name"]).lower() for action in plan["actions"])

    approved = parkpulse_api._copilot_object_action_plan("staff fatigue callout", objects, operator_approved=True, will_act=True)
    assert approved["overall_gate"] == "passed"
    assert approved["will_execute"] is True
    scorecard = parkpulse_api._copilot_reasoning_scorecard_for_action(approved["actions"][0], "staff fatigue callout", compact)
    assert parkpulse_api._copilot_reasoning_overall(scorecard) >= 80
    evaluation = parkpulse_api._copilot_reasoning_evaluation(
        "staff fatigue callout",
        compact,
        approved,
        [{"label": "Watch only", "verdict": "watch", "reason": "No mutation"}],
        {"mode": "passed", "state_mutation": True, "map_effect": "impact_replay"},
    )
    assert evaluation["verdict"] in {"strong", "review"}
    assert evaluation["checks"][1]["status"] == "pass"

    assert parkpulse_api._copilot_action_plan("medical first aid needed", {"selected_role": "react"}, {})["target"] == "medical"
    assert parkpulse_api._copilot_action_plan("security fight", {"selected_role": "react"}, {})["target"] == "security"
    assert parkpulse_api._copilot_action_plan("staff fatigue", {"selected_role": "proact"}, {})["target"] == "staff"
    assert parkpulse_api._copilot_action_plan("storm heat shelter", {"selected_role": "proact"}, {})["target"] == "energy"
    assert parkpulse_api._copilot_action_plan("food mobile order", {"selected_role": "react"}, {})["target"] == "traffic"
    assert parkpulse_api._copilot_action_plan("coaster queue", {"selected_role": "react"}, {})["target"] == "ride"
    assert parkpulse_api._copilot_action_plan("generic", {"selected_role": "scan"}, {"primary_zone_id": "foodCourt1"})["target"] == "traffic"
    assert parkpulse_api._copilot_action_plan("generic", {"selected_role": "scan"}, {})["id"] == "copilot_scan_reroute"


def test_api_ontology_routes_are_wrapped_with_state(monkeypatch):
    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation())
    monkeypatch.setattr(parkpulse_api, "read_persistent_ontology", lambda snapshot: {"status": "ready", "snapshot_keys": sorted(snapshot)})
    monkeypatch.setattr(parkpulse_api, "read_ontology_events", lambda limit: {"events": [{"id": "evt"}], "limit": limit})

    ontology = run(parkpulse_api.get_park_ontology())
    events = run(parkpulse_api.get_park_ontology_events(limit=3))
    assert ontology["status"] == "ready"
    assert "objects" in ontology["snapshot_keys"]
    assert events["limit"] == 3


def test_api_live_feed_impact_text_and_training_generation_wrappers(monkeypatch):
    assert "food court" in parkpulse_api._live_feed_controlled_impact_text("demand_spike", "food_retail", "x", "food_court")
    assert "staff worker" in parkpulse_api._live_feed_controlled_impact_text("callout", "hr_labor", "x", "staff_base")
    assert "hvac energy" in parkpulse_api._live_feed_controlled_impact_text("energy_spike", "maintenance", "create_work_order", "hvac")
    assert "ride coaster" in parkpulse_api._live_feed_controlled_impact_text("ride_failure", "maintenance", "create_work_order", "coaster")
    assert "weather operations" in parkpulse_api._live_feed_controlled_impact_text("storm_risk", "operations", "create_ops_alert", "park")
    assert "crowd security" in parkpulse_api._live_feed_controlled_impact_text("access_lane_block", "operations", "create_ops_alert", "lane")
    assert "ride coaster queue" in parkpulse_api._live_feed_controlled_impact_text("ride_failure", "operations", "create_ops_alert", "ride")
    assert "food guest demand" in parkpulse_api._live_feed_controlled_impact_text("demand_spike", "marketing", "redirect_offer", "food")
    assert "internal receiver" in parkpulse_api._live_feed_controlled_impact_text("custom", "ops", "custom", "target")
    assert "route recommendation" in parkpulse_api._live_feed_escalated_impact_text("crowd", "ops", "recommend_route_change", "zone")
    assert "guest message" in parkpulse_api._live_feed_escalated_impact_text("crowd", "ops", "draft_guest_message", "zone")
    assert "maintenance work order" in parkpulse_api._live_feed_escalated_impact_text("ride", "ops", "create_work_order", "zone")
    assert "redirect offer" in parkpulse_api._live_feed_escalated_impact_text("food", "ops", "redirect_offer", "zone")
    assert "simulated escalation" in parkpulse_api._live_feed_escalated_impact_text("other", "ops", "other", "zone")

    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation())
    monkeypatch.setattr(parkpulse_api, "_require_role_action", lambda *args, **kwargs: {"allowed": True})
    monkeypatch.setattr(parkpulse_api, "review_training_ledger", lambda limit=120: {"summary": {"training_candidate_count": 3}})
    monkeypatch.setattr(parkpulse_api, "live_feed_health", lambda state, limit=120: {"summary": {"ready_feed_count": 5}})
    monkeypatch.setattr(review_label_pipeline, "review_label_decision_ledger", lambda limit=200: {"summary": {"approved_label_count": 1}})
    monkeypatch.setattr(review_label_pipeline, "auto_label_recommended_candidates", lambda pipeline, reviewer, confidence_threshold: {"status": "labeled", "recorded_count": 1, "reviewer": reviewer, "threshold": confidence_threshold})
    monkeypatch.setattr(review_label_pipeline, "build_review_label_pipeline", lambda **kwargs: {"summary": {"limit": kwargs.get("limit")}, "items": [1]})
    monkeypatch.setattr(park_actual_training, "actual_training_status", lambda *args, **kwargs: {"status": "ready", "sample_count": 100})
    monkeypatch.setattr(training_readiness, "build_training_readiness_report", lambda **kwargs: {"status": "ready", "min_review_labels": kwargs["min_review_labels"]})
    monkeypatch.setattr(controlled_training_generation, "latest_controlled_training_pack", lambda: {"status": "latest"})
    monkeypatch.setattr(controlled_training_generation, "generate_controlled_training_pack", lambda **kwargs: {"status": "generated", "max_examples": kwargs["max_examples"], "write_artifacts": kwargs["write_artifacts"]})

    auto_label = run(parkpulse_api.park_review_label_auto_label(object(), {"minReviewLabels": 2, "minOutcomeRows": 4, "confidenceThreshold": 0.8, "reviewer": "unit"}))
    assert auto_label["status"] == "labeled"
    assert auto_label["pipeline_before"]["limit"] == 200
    assert run(parkpulse_api.park_controlled_training_generation_latest(object()))["status"] == "latest"
    generated = run(
        parkpulse_api.park_controlled_training_generation(
            object(),
            {"maxExamples": 5, "writeArtifacts": False, "autoLabelHighConfidence": True, "confidenceThreshold": 0.75},
        )
    )
    assert generated["status"] == "generated"
    assert generated["review_label_auto_label"]["recorded_count"] == 1


def test_main_customer_public_details_and_review_label_summary(monkeypatch):
    monkeypatch.setattr(review_label_pipeline, "review_label_decision_ledger", lambda limit=1000: {"summary": {"approved_label_count": 4}})
    enriched = main._review_ledger_with_label_decisions({"summary": {"training_candidate_count": 9}})
    assert enriched["summary"]["training_candidate_count"] == 13

    details = main._customer_public_park_details(compact_state(), station={"id": "station1", "title": "Front Kiosk", "zoneId": "foodCourt1", "waitMins": 2})
    assert details["status"] == "ready"
    assert details["station"]["name"] == "Front Kiosk"
    assert details["weather"]["guest_note"].startswith("It is hot")
    assert details["venue_map"]["emergency_access"]["status"] == "blocked"
    assert details["recommended_public_options"]["best_food"]["name"] == "Food Court B"
    assert details["public_alerts"][0]["title"] == "Parade route update"
    assert all("Staff policy" != alert["title"] for alert in details["public_alerts"])

    route_answer = main._customer_support_fallback_response({"mode": "route", "question": "where next", "station": {"zoneId": "foodCourt1"}}, compact_state())
    phone_answer = main._customer_support_fallback_response({"mode": "phone"}, compact_state(), reason="unit")
    rec_answer = main._customer_support_fallback_response({"mode": "recommendation"}, compact_state())
    assert route_answer["customer_action"]["label"] == "Route shown"
    assert phone_answer["customer_action"]["label"] == "Sent to phone"
    assert rec_answer["customer_action"]["label"] == "Recommendation ready"
    assert main._customer_agent_fallback_reason('{"error": "GEMINI_API_KEY missing"}') == "Gemini credentials are not configured for this backend runtime."
    assert main._customer_agent_tool_for_mode("phone") == "customer_send_to_phone"


async def _asgi_json(method, path, payload=None, query_string=b""):
    body = json.dumps(payload or {}).encode("utf-8")
    sent = []
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    await main.app(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string if isinstance(query_string, bytes) else str(query_string).encode("utf-8"),
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
        send,
    )
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    response_body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, json.loads(response_body.decode("utf-8") or "{}")


def test_main_session_routes_and_fallback_branches(monkeypatch):
    async def state_ok():
        return compact_state()

    async def state_fails():
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(main, "_fast_park_state_lite", state_ok)
    monkeypatch.setattr(main, "get_agent_session", lambda session_id: {"mode": "get", "session_id": session_id})
    monkeypatch.setattr(main, "capability_handshake", lambda session_id, payload: {"mode": "capabilities", "payload": payload})
    monkeypatch.setattr(main, "intent_handshake", lambda session_id, payload: {"mode": "intent", "payload": payload})
    monkeypatch.setattr(main, "propose_plan", lambda session_id, payload, park_state=None: {"mode": "propose", "has_state": park_state is not None})
    monkeypatch.setattr(main, "counter_proposal", lambda session_id, payload, park_state=None: {"mode": "counter", "has_state": park_state is not None})
    monkeypatch.setattr(main, "commit_plan", lambda session_id, payload: {"mode": "commit", "payload": payload})
    monkeypatch.setattr(main, "evaluate_policy_action", lambda session_id, payload: {"mode": "policy", "payload": payload})
    monkeypatch.setattr(main, "monitor_session", lambda session_id, payload, park_state=None: {"mode": "monitor", "event": payload["event"], "has_state": park_state is not None})
    monkeypatch.setattr(main, "escalate_agent_session", lambda session_id, payload: {"mode": "escalate", "payload": payload})
    monkeypatch.setattr(main, "session_protocol_receipt", lambda session_id, payload: {"mode": "receipt", "payload": payload})
    monkeypatch.setattr(main, "close_agent_session", lambda session_id, payload: {"mode": "close", "payload": payload})

    assert run(_asgi_json("GET", "/api/park/session/s1")) == (200, {"mode": "get", "session_id": "s1"})
    assert run(_asgi_json("POST", "/api/park/session/s1/capabilities", {"cap": True}))[1]["mode"] == "capabilities"
    assert run(_asgi_json("POST", "/api/park/session/s1/intent", {"intent": "queue"}))[1]["payload"]["intent"] == "queue"
    assert run(_asgi_json("POST", "/api/park/session/s1/propose", {"x": 1}))[1]["has_state"] is True
    assert run(_asgi_json("POST", "/api/park/session/s1/counter", {"x": 1}))[1]["has_state"] is True
    assert run(_asgi_json("POST", "/api/park/session/s1/commit", {"ok": True}))[1]["mode"] == "commit"
    assert run(_asgi_json("POST", "/api/park/session/s1/policy-check", {"action": "reroute"}))[1]["mode"] == "policy"
    assert run(_asgi_json("GET", "/api/park/session/s1/monitor"))[1] == {"mode": "monitor", "event": "live", "has_state": True}
    assert run(_asgi_json("POST", "/api/park/session/s1/escalate", {"why": "unit"}))[1]["mode"] == "escalate"
    assert run(_asgi_json("GET", "/api/park/session/s1/receipt"))[1]["mode"] == "receipt"
    assert run(_asgi_json("POST", "/api/park/session/s1/close", {"done": True}))[1]["mode"] == "close"

    monkeypatch.setattr(main, "_fast_park_state_lite", state_fails)
    assert run(_asgi_json("POST", "/api/park/session/s1/propose", {"x": 1}))[1]["has_state"] is False
    assert run(_asgi_json("POST", "/api/park/session/s1/counter", {"x": 1}))[1]["has_state"] is False
    assert run(_asgi_json("POST", "/api/park/session/s1/monitor", {"event": "tick"}))[1] == {"mode": "monitor", "event": "tick", "has_state": False}

    monkeypatch.setattr(main, "get_agent_session", lambda session_id: (_ for _ in ()).throw(KeyError("missing")))
    assert run(_asgi_json("GET", "/api/park/session/missing"))[0] == 404
    monkeypatch.setattr(main, "get_agent_session", lambda session_id: (_ for _ in ()).throw(PermissionError("denied")))
    assert run(_asgi_json("GET", "/api/park/session/denied"))[0] == 403


def test_main_agent_role_and_refinement_fast_fallbacks(monkeypatch):
    async def role_payload(message, mode, route):
        return {"selected_role": "qa", "message": message, "route": route}

    async def react_payload(message, mode, route):
        return {"selected_role": "react", "message": message, "route": route}

    async def proact_payload(message, mode, route):
        return {"selected_role": "proact", "message": message, "route": route}

    async def customer_payload(message, mode, route):
        return {"selected_role": "customer", "message": message, "route": route}

    monkeypatch.setattr(main, "_qa_role_payload", role_payload)
    monkeypatch.setattr(main, "_react_role_payload", react_payload)
    monkeypatch.setattr(main, "_proact_role_payload", proact_payload)
    monkeypatch.setattr(main, "_customer_role_hot_path_payload", customer_payload)
    monkeypatch.setattr(main, "_scan_role_payload", lambda message, mode, route: {"selected_role": "scan", "message": message, "route": route})

    for selected in ("qa", "react", "proact", "customer", "scan"):
        monkeypatch.setattr(main, "route_agent_role", lambda message, mode, selected=selected: {"selected_role": selected})
        assert run(main._agent_role_run_payload("unit", mode=selected))["selected_role"] == selected

    async def fail_refinement(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(gemini_hard_timeout, "generate_gemini_json_hard_timeout", fail_refinement)
    refinement = run(
        main._agent_role_refinement_payload(
            "keep plan",
            {
                "selected_role": "react",
                "role_receipt": {"scenario_key": "ride_down", "learning_update": {"status": "stored"}},
                "run_telemetry": {"delivery": {"dispatches": [{"channel": "guest", "status": "sent", "payload": {"id": "d1"}}]}},
            },
        )
    )
    assert refinement["status"] == "fallback"
    assert refinement["selected_role"] == "react"
    assert refinement["scenario_key"] == "ride_down"


def test_main_runtime_wrappers_use_fast_fallback_and_schedule_refinement(monkeypatch):
    scheduled = []

    monkeypatch.setattr(main, "_parkpulse_app", object())
    monkeypatch.setattr(main, "_sync_full_response_enabled", lambda: False)
    monkeypatch.setattr(main, "_timeout_tiers", lambda: {"operator_full_load_seconds": 0.1, "operator_command_seconds": 0.1, "agent_run_full_load_seconds": 0.1, "agent_run_seconds": 0.1})
    monkeypatch.setattr(main, "_full_runtime_status", lambda: {"loaded": True})
    monkeypatch.setattr(
        main,
        "_store_run_receipt",
        lambda payload, **kwargs: {**payload, "run_receipt": {"id": f"receipt-{kwargs.get('kind')}"}},
    )
    monkeypatch.setattr(main, "_schedule_operator_command_refinement", lambda message, mode, execute, receipt_id: scheduled.append(("operator", receipt_id, message)))
    monkeypatch.setattr(main, "_schedule_agent_run_refinement", lambda payload, receipt_id, **kwargs: scheduled.append(("agent", receipt_id, kwargs.get("message"))))
    monkeypatch.setattr(main, "_metric", lambda name: None)
    monkeypatch.setattr(main, "_attach_live_weather_gate_to_payload", lambda payload: payload)
    for name in (
        "live_weather_state_evidence",
        "live_ride_ops_state_evidence",
        "live_guest_flow_state_evidence",
        "live_staffing_state_evidence",
        "live_food_ops_state_evidence",
        "live_operator_signal_state_evidence",
        "live_weather_training_gate",
        "live_ride_ops_training_gate",
        "live_guest_flow_training_gate",
        "live_staffing_training_gate",
        "live_food_ops_training_gate",
        "live_operator_signal_training_gate",
    ):
        monkeypatch.setattr(main, name, lambda name=name: {"status": "unit", "source": name})

    operator = run(main._build_operator_payload_with_runtime("food court backlog", "auto", False, "unit"))
    agent = run(main._build_agent_run_payload_with_runtime({"message": "coaster down", "scenario_key": "ride_down", "execute": False}, "unit"))

    assert operator["status"] == "bounded_fallback"
    assert operator["runtime_proof"]["receipt_upgrade_status"] == "pending"
    assert agent["status"] == "bounded_fallback"
    assert agent["scenario_key"] == "ride_down"
    assert scheduled == [
        ("operator", "receipt-operator_command", "food court backlog"),
        ("agent", "receipt-agent_run", "coaster down"),
    ]

    async def fail_full_module(timeout):
        raise RuntimeError("full runtime cold")

    monkeypatch.setattr(main, "_parkpulse_app", None)
    monkeypatch.setattr(main, "_get_full_module_for_first_response", fail_full_module)
    scheduled.clear()
    error_fallback = run(main._build_agent_run_payload_with_runtime({"message": "staff callout", "scenario_key": "staff_shortage"}, "timeout"))
    assert error_fallback["status"] == "bounded_fallback"
    assert "full runtime cold" in error_fallback["runtime_proof"]["fallback_reason"]
    assert scheduled and scheduled[0][0] == "agent"


def test_parkpulse_api_live_feed_agent_run_blocked_and_complete(monkeypatch):
    health_ready = {
        "summary": {"persisted_event_count": 3, "ready_feed_count": 5, "required_feed_count": 5, "missing_or_weak_feed_count": 0},
        "feeds": [
            {
                "source": "operator_signal",
                "label": "Operator Signal",
                "owner": "ops",
                "status": "ready",
                "latest_signal_type": "food_pressure",
                "confidence": 0.91,
                "age_seconds": 3,
                "latest_event_id": "evt-1",
                "value": {"pickupEtaMinutes": 22, "mobileOrderBacklog": 45},
            },
            {"source": "ride_ops", "label": "Ride Ops", "owner": "rides", "status": "ready", "latest_signal_type": "queue", "confidence": 0.83, "value": {"waitMins": 70}},
        ],
    }
    refresh_calls = []

    async def fake_health(limit=120):
        return health_ready

    async def fake_refresh(payload):
        refresh_calls.append(payload)
        return {"status": "refreshed", "after_feeds": health_ready["feeds"]}

    async def fake_agent_run(request):
        return {
            "status": "complete",
            "role_agent_proposals": {
                "park_profile_summary": {"venue": "unit"},
                "cooperation_graph": {"nodes": ["ops"]},
                "food_retail": {"department": "food_retail", "requested_tool": "dispatch_worker_task", "department_reasoning": {"candidate_actions": [{"score": 0.7}], "forecast": {}, "memory_carry_forward": {}}},
            },
        }

    monkeypatch.setattr(parkpulse_api, "_live_feed_health_payload", fake_health)
    monkeypatch.setattr(parkpulse_api, "_refresh_due_live_feeds_payload", fake_refresh)
    monkeypatch.setattr(parkpulse_api, "_live_feed_memory_priors_from_dashboard", lambda live_case: {"food_retail": {"outcome_id": "prior-1"}})
    monkeypatch.setattr(parkpulse_api, "_live_feed_ml_policy_evidence", lambda live_case: {"status": "ready"})
    monkeypatch.setattr(parkpulse_api, "park_agent_run", fake_agent_run)
    monkeypatch.setattr(parkpulse_api, "_build_live_feed_alternative_action_negotiation", lambda proposals: {"status": "ready"})
    monkeypatch.setattr(parkpulse_api, "_build_live_feed_cooperation_graph", lambda proposals, live_case: {"nodes": ["fallback"]})
    monkeypatch.setattr(parkpulse_api, "_controlled_live_feed_tool_executor_run", lambda payload, execute=False: {"receipts": []})
    monkeypatch.setattr(parkpulse_api, "_build_live_feed_hard_decision_follow_through", lambda payload: {"status": "ready"})
    monkeypatch.setattr(parkpulse_api, "_apply_risk_escalation_validation_mode", lambda payload, mode: {**payload, "risk_mode": mode})
    monkeypatch.setattr(parkpulse_api, "_build_live_feed_risk_escalation_approval", lambda payload, enabled=False: {"enabled": enabled})
    monkeypatch.setattr(parkpulse_api, "_risk_escalated_live_feed_tool_executor_run", lambda payload, execute=False: {"status": "skipped"})
    monkeypatch.setattr(parkpulse_api, "_controlled_live_feed_receiver_delivery_proof", lambda payload: {"status": "ready"})
    monkeypatch.setattr(parkpulse_api, "_risk_escalation_receiver_delivery_proof", lambda payload: {"status": "skipped"})

    async def fake_controlled_impact(payload):
        return {"status": "simulated"}

    async def fake_risk_impact(payload):
        return {"status": "risk_simulated"}

    monkeypatch.setattr(parkpulse_api, "_apply_controlled_live_feed_simulated_ops_impact", fake_controlled_impact)
    monkeypatch.setattr(parkpulse_api, "_apply_risk_escalation_simulated_ops_impact", fake_risk_impact)
    monkeypatch.setattr(parkpulse_api, "_build_live_feed_outcome_measurement", lambda payload, refresh: {"status": "measured", "refresh_status": refresh.get("status")})
    monkeypatch.setattr(parkpulse_api, "_record_live_feed_controlled_outcome_memory", lambda payload: {"status": "stored"})
    monkeypatch.setattr(parkpulse_api, "_tool_use_clarity_from_run", lambda payload: {"status": "clear"})

    blocked_health = {**health_ready, "summary": {"persisted_event_count": 0, "ready_feed_count": 1}}

    async def blocked_health_payload(limit=120):
        return blocked_health

    monkeypatch.setattr(parkpulse_api, "_live_feed_health_payload", blocked_health_payload)
    blocked = run(
        parkpulse_api.park_live_feed_agent_run(
            parkpulse_api.LiveFeedAgentRunRequest(refresh_stale=True, require_persisted_events=True, min_ready_feeds=3)
        )
    )
    assert blocked["status"] == "blocked"
    assert len(blocked["readiness_issues"]) == 2
    assert refresh_calls[-1]["stale_only"] is False

    monkeypatch.setattr(parkpulse_api, "_live_feed_health_payload", fake_health)
    complete = run(
        parkpulse_api.park_live_feed_agent_run(
            parkpulse_api.LiveFeedAgentRunRequest(
                refresh_stale=True,
                scenario_key_hint="live-food",
                generated_issue={"kind": "food_pressure", "targetId": "foodCourt1"},
                require_persisted_events=True,
                min_ready_feeds=2,
                measure_post_action=False,
                risk_escalation_validation_mode="missing_controls",
                allow_risk_escalation=True,
            )
        )
    )
    assert complete["mode"] == "live_feed_agent_run"
    assert complete["live_feed_case"]["scenario_key"] == "live-food"
    assert complete["live_feed_post_action_refresh"]["status"] == "skipped"
    assert complete["risk_escalation_approval"]["enabled"] is True
    assert complete["tool_use_clarity"]["status"] == "clear"
    assert refresh_calls[-1]["stale_only"] is True


def test_parkpulse_api_industrial_dossier_packet_ready_path():
    case_id = "case-unit"
    case_row = {"caseId": case_id, "productionReady": False, "blockingGaps": ["field proof"], "validationRuns": [1], "acceptanceGate": "review"}
    payload = {
        "standard": "unit-standard",
        "generatedFrom": ["unit"],
        "simulationClock": {"minute": 42},
        "auditManifest": {"qualityGate": {"status": "ready"}},
        "portfolioOperatingModel": {"mode": "industrial_portfolio_operating_model", "assetInventory": [1], "spatialNetwork": [1], "coverageReadiness": {"status": "ready"}},
        "portfolioRiskRanking": {"mode": "industrial_portfolio_risk_ranking", "rankingRows": [{"caseId": case_id, "rank": 1}], "operatingQueue": [case_id]},
        "productionEvidenceGapRegister": {"mode": "industrial_production_evidence_gap_register", "caseRows": [case_row], "feedReadinessRows": [1]},
        "fieldReplayValidationHarness": {"mode": "industrial_field_replay_validation_harness", "caseRows": [{**case_row, "replayDatasetSpec": {"id": "ds"}}]},
        "capacityCertificationLedger": {"mode": "industrial_capacity_certification_ledger", "caseRows": [{**case_row, "capacityFindings": [1], "certificationState": "blocked"}]},
        "slaEscalationClock": {"mode": "industrial_sla_escalation_clock", "caseRows": [{**case_row, "clockRows": [1], "escalationAuthority": "ops"}]},
        "receiverExecutionContractLedger": {"mode": "industrial_receiver_execution_contract_ledger", "caseRows": [{**case_row, "contractRows": [1]}]},
        "incidentCommandDecisionLog": {"mode": "industrial_incident_command_decision_log", "caseRows": [{**case_row, "decisionRecord": {"id": "d"}, "auditEvent": {"id": "a"}}]},
        "industrialActionReplayLedger": {"mode": "industrial_action_replay_ledger", "caseRows": [{**case_row, "timelineFrames": [1], "closedLoopWatch": {"status": "watch"}}]},
        "physicalMovementProofLedger": {"mode": "industrial_physical_movement_proof_ledger", "caseRows": [{**case_row, "mapObjectBinding": [1], "pathProofRows": [1], "queueProofRows": [1]}]},
        "telemetryAcceptanceLedger": {"mode": "industrial_telemetry_acceptance_ledger", "caseRows": [{**case_row, "acceptanceGateRows": [1], "sourceContract": {"id": "s"}, "closedLoopAcceptance": {"status": "blocked"}}]},
        "outcomeAccountabilityLedger": {"mode": "industrial_outcome_accountability_ledger", "caseRows": [{**case_row, "expectedOutcome": "relief", "observedEvidenceStatus": "pending", "rollbackPosture": "ready"}]},
        "industrialCaseFileSynthesis": {"mode": "industrial_case_file_synthesis", "caseFiles": [{"caseId": case_id, "caseNarrative": "unit", "proofStack": [1], "accountability": {"owner": "ops"}}]},
        "externalSystemExecutionEvidence": {"mode": "industrial_external_system_execution_evidence", "caseRows": [{**case_row, "evidenceRows": [1]}]},
        "industrialDossierCompletenessAudit": {"mode": "industrial_dossier_completeness_audit", "auditRows": [{"caseId": case_id, "proofFamilies": [1], "promotionBoundary": "blocked"}]},
        "liveEvidenceDriftMonitor": {"mode": "industrial_live_evidence_drift_monitor", "driftRows": [{"caseId": case_id, "liveSignals": [1], "requiredRecheck": "yes"}]},
        "observedOutcomeCalibrationLedger": {"mode": "industrial_observed_outcome_calibration_ledger", "calibrationRows": [{"caseId": case_id, "variance": "low", "trustDecision": "review"}]},
        "productionDataIngestionContract": {"mode": "industrial_production_data_ingestion_contract", "caseRows": [{**case_row, "feedContracts": [1], "graduationCriteria": [1]}]},
        "industrialPromotionCertificationGate": {"mode": "industrial_promotion_certification_gate", "certificationRows": [{"caseId": case_id, "certificationChecks": [1], "releaseBoundary": "blocked"}]},
        "fieldTrialProtocolLedger": {"mode": "industrial_field_trial_protocol_ledger", "protocolRows": [{"caseId": case_id, "trialScope": "unit", "stopRules": [1]}]},
        "fieldTrialExecutionEvidenceLedger": {"mode": "industrial_field_trial_execution_evidence_ledger", "caseRows": [{**case_row, "observationCaptures": [1], "trialOutcomeDisposition": "pending"}]},
        "fieldTrialCloseoutLedger": {"mode": "industrial_field_trial_closeout_ledger", "closeoutRows": [{"caseId": case_id, "trialResultRecord": {"id": "r"}, "promotionDecision": "hold"}]},
        "industrialOperatingTimelineLedger": {"mode": "industrial_operating_timeline_ledger", "timelineRows": [{"caseId": case_id, "eventRows": [1], "mapBindingSummary": {"id": "m"}}]},
        "varianceRootCauseLedger": {"mode": "industrial_variance_root_cause_ledger", "rootCauseRows": [{"caseId": case_id, "rootCauseRows": [1], "reuseDecision": "hold"}]},
        "industrialReviewDispositionLedger": {"mode": "industrial_review_disposition_ledger", "dispositionRows": [{"caseId": case_id, "signoffMatrix": [1], "reviewDisposition": "hold"}]},
        "industrialAuditExportManifest": {"mode": "industrial_audit_export_manifest", "packageRows": [{"caseId": case_id, "packageHash": "hash", "artifactRows": [1]}]},
        "dataLineageCertificationLedger": {"mode": "industrial_data_lineage_certification_ledger", "certificationRows": [{"caseId": case_id, "sourceSystemRows": [1], "certificationDecision": "hold"}]},
        "policyRiskControlLedger": {"mode": "industrial_policy_risk_control_ledger", "controlRows": [{"caseId": case_id, "controlRows": [1], "sensitiveFlags": [1]}]},
        "caseWorkOrderExecutionLedger": {"mode": "industrial_case_work_order_execution_ledger", "caseRows": [{**case_row, "workOrders": [1], "acknowledgementPlan": [1]}]},
        "fieldReceiptReconciliationLedger": {"mode": "industrial_field_receipt_reconciliation_ledger", "caseRows": [{**case_row, "receiptRows": [1], "productionBoundary": "blocked"}]},
        "releaseBoardExceptionLedger": {"mode": "industrial_release_board_exception_ledger", "exceptionRows": [{"caseId": case_id, "exceptionDecision": "no", "signoffRows": [1]}]},
        "scenarioCoverageCertificationLedger": {"mode": "industrial_scenario_coverage_certification_ledger", "certificationRows": [{"caseId": case_id, "drillFamilyRows": [1], "productionBoundary": "blocked"}]},
        "operatorCompetencyEvaluationLedger": {"mode": "industrial_operator_competency_evaluation_ledger", "caseRows": [{**case_row, "evaluationTasks": [1], "scoringRubric": [1]}]},
        "causalEpisodeTrainingLedger": {"mode": "industrial_causal_episode_training_ledger", "caseRows": [{**case_row, "episodeFrames": [1], "physicalProofSummary": {"id": "p"}}]},
        "simulationValidityCalibrationLedger": {"mode": "industrial_simulation_validity_calibration_ledger", "caseRows": [{**case_row, "assumptionRows": [1], "falsificationChecks": [1]}]},
        "fieldObservationProtocolLedger": {"mode": "industrial_field_observation_protocol_ledger", "caseRows": [{**case_row, "stationRows": [1], "measurementProtocol": {"id": "m"}}]},
        "fieldEvidenceCaptureLedger": {"mode": "industrial_field_evidence_capture_ledger", "caseRows": [{**case_row, "formRows": [1], "custody": {"id": "c"}}]},
        "fieldEvidenceSampleLedger": {"mode": "industrial_field_evidence_sample_ledger", "caseRows": [{**case_row, "recordRows": [1], "custodySummary": {"id": "c"}}]},
        "fieldEvidenceAdjudicationLedger": {"mode": "industrial_field_evidence_adjudication_ledger", "caseRows": [{**case_row, "metricAdjudications": [1], "releaseImpact": "hold"}]},
        "fieldEvidenceRemediationLedger": {"mode": "industrial_field_evidence_remediation_ledger", "caseRows": [{**case_row, "remediationRows": [1], "releaseHold": True}]},
        "fieldEvidenceRemediationExecutionLedger": {"mode": "industrial_field_evidence_remediation_execution_ledger", "caseRows": [{**case_row, "executionRows": [1], "holdClearance": "no"}]},
        "fieldEvidenceReleaseClearanceLedger": {"mode": "industrial_field_evidence_release_clearance_ledger", "caseRows": [{**case_row, "signoffMatrix": [1], "clearancePacket": {"id": "p"}}]},
        "spatialExecutionDrillLedger": {"mode": "industrial_spatial_execution_drill_ledger", "caseRows": [{**case_row, "drillFrames": [1], "stopRules": [1], "drillPacket": {"id": "d"}}]},
        "observedDrillVarianceLedger": {"mode": "industrial_observed_drill_variance_ledger", "caseRows": [{**case_row, "varianceRows": [1], "reuseGate": "hold", "variancePacket": {"id": "v"}}]},
        "industrialAcceptanceCertificationLedger": {"mode": "industrial_acceptance_certification_ledger", "caseRows": [{**case_row, "proofFamilyRows": [1], "signoffPosture": "hold", "certificationPacket": {"id": "c"}}]},
        "productionEvidenceAcquisitionLedger": {"mode": "industrial_production_evidence_acquisition_ledger", "caseRows": [{**case_row, "feedAcquisitions": [1], "graduationStages": [1], "acquisitionPacket": {"id": "a"}}]},
        "portfolioCoverage": {"summary": "unit"},
        "industrialStandardsMatrix": {"mode": "industrial_standards_matrix", "standards": [1], "summary": {"status": "ready"}},
        "industrialDeploymentReadiness": {"mode": "industrial_deployment_readiness", "deploymentState": "demo_ready_not_production_ready", "productionBlockers": [1]},
        "industrialOwnershipModel": {"mode": "industrial_ownership_raci_model", "domainRaci": [1], "receiverRaci": [1], "productionBlockerOwners": [1]},
        "coverageMatrix": [{"domain": "queue", "coverage": "ready"}],
    }
    branch_ids = ["no_action", "fast_local_action", "governed_agent_action"]
    dossier = {
        "id": case_id,
        "sourceConflictId": "conflict-unit",
        "title": "Unit industrial packet",
        "domain": "queue",
        "caseType": "operating_case",
        "severity": "high",
        "mapFocus": ["foodCourt1"],
        "quality": {"status": "ready"},
        "operatingThesis": {"claim": "bounded action", "whyNow": "live risk", "notJustMetric": "physical proof"},
        "policyReasoning": {"applies": ["P1"], "blocks": ["no broad reroute"]},
        "verificationPlan": {"successMetric": "relief", "rollbackTrigger": "regression", "watchConditions": ["wait"]},
        "auditStandard": {"traceKeys": ["k"], "minimumEvidence": ["e"]},
        "evidenceProvenance": [{"sourceLayer": "live"}],
        "receiverReadiness": [{"receiver": "guest"}],
        "actionTrainingFrame": [{"branch": branch, "operatorMeaning": branch} for branch in branch_ids],
        "simulatedBranchComparison": {
            "mode": "dossier_three_branch_physical_simulation",
            "horizon_minutes": 15,
            "selected_branch": "governed_agent_action",
            "rejected_branch": "fast_local_action",
            "summary": {"winner": "governed"},
            "branches": [{"id": branch, "label": branch, "score": 80, "raw_score": 80, "score_adjustment": 0, "decision_basis": {"why": "unit"}, "delta_from_now": {"wait": -5}} for branch in branch_ids],
        },
        "mapObjectEvidenceIndex": {"mode": "industrial_map_object_evidence_index", "objectRows": [1], "pathRows": [1], "queueRows": [1]},
        "parkRealityModel": {"mode": "case_specific_park_reality_model", "localTopology": [1], "capacityEnvelope": [1]},
        "liveOperatingSceneModel": {"mode": "industrial_live_operating_scene_model", "actors": [1], "physicalScene": [1], "bottlenecks": [1], "agentBeliefState": [1]},
        "causalGraph": {"mode": "typed_operating_causal_graph", "nodes": [1], "edges": [1]},
        "counterfactualReplay": {"mode": "counterfactual_branch_replay_matrix", "rows": [1]},
        "branchPhysicalImpactMatrix": {"mode": "industrial_branch_physical_impact_matrix", "branchRows": [{"branch": "governed_agent_action"}], "subsystemMovement": [1]},
        "actionConsequenceSimulation": {"mode": "industrial_action_consequence_simulation", "consequenceFrames": [1], "branchOutcomeSummary": [1]},
        "commercialImpactLedger": {"mode": "industrial_commercial_impact_ledger", "rows": [1]},
        "accessibilityEquityImpact": {"mode": "industrial_accessibility_equity_impact", "protectedCohorts": [1], "routeAccessChecks": [1], "fairnessChecks": [1]},
        "resourceFeasibilityMatrix": {"mode": "industrial_resource_feasibility_matrix", "receiverExecutionRows": [1], "branchFeasibilityComparison": [1]},
        "policyClauseTrace": {"mode": "industrial_policy_clause_trace", "clauseRows": [1], "branchPolicyVerdicts": [1]},
        "spatialPhysicsEnvelope": {"mode": "industrial_spatial_physics_envelope", "routePhysics": [1], "queueGeometry": [1]},
        "physicalPropagationModel": {"mode": "industrial_physical_propagation_model", "chain": [1], "branchPropagationEffects": [1], "tripwires": [1]},
        "historicalPrecedentMatrix": {"mode": "industrial_historical_precedent_matrix", "matchedPrecedents": [1], "branchPrecedentVerdicts": [1]},
        "guestCommunicationPlan": {"mode": "industrial_guest_communication_plan", "audiencePlans": [1], "channelPlan": [1], "promiseBoundaries": [1]},
        "behavioralResponseModel": {"mode": "industrial_behavioral_response_model", "segmentBehavior": [1], "staffAndReceiverResponse": [1], "branchBehaviorComparison": [1]},
        "operationalConstraintRegister": {"mode": "industrial_operational_constraint_register", "hardConstraints": [1], "branchConstraintVerdicts": [1], "goNoGo": "hold"},
        "releaseDecisionRecord": {"mode": "industrial_release_decision_record", "signoffMatrix": [1], "approvedVersion": "v1", "postReleaseObligations": [1]},
        "releaseAuthorityDecision": {"mode": "industrial_release_authority_decision", "authorityChecks": [1], "liveActionAuthority": "authorized_after_human_signoff", "autoExecuteAllowed": False},
        "executionReadinessProof": {"mode": "industrial_execution_readiness_proof", "executionChecks": [1], "requiredBeforeDispatch": [1], "caseSceneEvidence": [1], "readyForLiveExecution": False},
        "releaseRemediationPlan": {"mode": "industrial_release_remediation_plan", "tasks": [1], "recheckSequence": [1]},
        "operatingProcedureDelta": {"mode": "industrial_operating_procedure_delta", "procedureDeltas": [1], "runbookStepUpdates": [1], "policyPatchCandidates": [1], "promotionGate": "hold"},
        "decisionReproducibilityManifest": {"mode": "industrial_decision_reproducibility_manifest", "inputArtifacts": [1], "simulatorVersion": "v1", "branchIds": branch_ids, "expectedDeterministicOutputs": [1], "replayInstructions": [1], "reproducibilityGate": "ready"},
        "chainOfCustodyAuditLog": {"mode": "industrial_chain_of_custody_audit_log", "custodyRows": [1], "immutableTraceCheckpoints": [1], "auditReplayInstructions": [1]},
        "fieldCalibrationBacktestPlan": {"mode": "industrial_field_calibration_backtest_plan", "requiredDatasets": [1], "backtestSuites": [1], "acceptanceThresholds": [1], "driftTriggers": [1]},
        "operatingScorecard": {"mode": "industrial_operating_scorecard", "scoreRows": [1], "tradeoffLedger": [1]},
        "assumptionSensitivityAnalysis": {"mode": "industrial_assumption_sensitivity_analysis", "stressTests": [1], "flipConditions": [1]},
        "operationalStressRehearsal": {"mode": "industrial_operational_stress_rehearsal", "rehearsalScenarios": [1], "escalationTriggers": [1]},
        "independentReviewBoard": {"mode": "independent_operating_review_board", "reviews": [1], "releaseDecision": "hold"},
        "spatialCausalityTrace": {"branchSpatialEffects": [1]},
        "governedApprovalPackage": {"receiverWrites": [1]},
        "dataQualityCalibration": {"confidenceScore": 0.9},
        "telemetryContract": {"mode": "industrial_case_telemetry_contract", "sourceBindings": [1], "decisionReadiness": {"missingRequiredLayers": []}},
        "fieldSignalReconciliation": {"mode": "industrial_field_signal_reconciliation", "sourceRows": [1], "crossChecks": [1]},
        "decisionTelemetrySnapshot": {"mode": "industrial_decision_telemetry_snapshot", "queueRows": [1], "thresholdBreaches": [1], "sourceLineage": [1], "productionAcceptanceGates": [1], "telemetryCertification": [1], "freshness": [1]},
        "fieldExecutionHandoff": {"mode": "industrial_field_execution_handoff", "dispatches": [1], "acknowledgementGates": [1]},
        "caseExecutionRunbook": {"lifecycle": [1]},
        "closedLoopVerification": {"mode": "closed_loop_verification_plan", "observationWindows": [1], "projectedVsObservedChecks": [1]},
    }

    packet = parkpulse_api.build_industrial_dossier_packet(payload, dossier)

    assert packet["status"] == "ready"
    assert packet["caseHeader"]["id"] == case_id
    assert packet["machineReadable"]["branchProofReady"] is True
    assert packet["machineReadable"]["portfolioContextReady"] is True
    assert packet["portfolioContext"]["caseDomainCoverage"]["coverage"] == "ready"


def test_main_golden_and_command_center_routes(monkeypatch):
    monkeypatch.setattr(park_simulation, "park_simulation", FakeParkSimulation())
    monkeypatch.setattr(agent_ops_ledger, "build_operational_backlog", lambda state: {"unresolvedCount": 2, "enterpriseSummary": {"answer": "Two risks open."}})
    monkeypatch.setattr(
        agent_ops_ledger,
        "read_agent_ops_ledger",
        lambda limit=25: {
            "items": [
                {
                    "id": "trace-1",
                    "mode": "war_room_sop_patch_rerun",
                    "selectedAction": "Bounded split flow",
                    "summary": "Trace summary",
                    "evalScore": 91,
                    "memoryId": "mem-1",
                    "gate": "passed",
                    "traceEvents": [{"phase": "policy", "label": "Policy", "message": "Gate passed."}],
                }
            ]
        },
    )
    monkeypatch.setattr(agent_ops_ledger, "record_agent_ops_record", lambda record: {**record, "recorded": True})
    monkeypatch.setattr(park_delivery, "latest_dispatches", lambda limit=25: [{"id": "dispatch-1", "channel": "guest"}])
    monkeypatch.setattr(park_signal_intake, "latest_signals", lambda limit=25: {"signals": [{"summary": "Food pressure", "confidence": 0.88}]})
    monkeypatch.setattr(park_audit_agent, "build_audit_snapshot", lambda state: {"summary": {"criticalAnomalies": 1}, "anomalies": []})
    monkeypatch.setattr(incident_analytics, "build_incident_analytics", lambda **kwargs: {"tickets": [{"id": "ticket-1"}]})

    def fake_tool(tool, state, payload=None, trace_context=None):
        output = {"status": "ok", "overall": 0.9, "scorecard": {"overall": 88}, "memory_id": "memory-1"}
        if tool == "validate_policy" and payload and (payload.get("action") or {}).get("id") == "broad_reroute":
            output = {"status": "ok", "gate_status": "blocked"}
        elif tool == "validate_policy":
            output = {"status": "ok", "gate_status": "pending_operator_approval"}
        return {"tool": tool, "agent_id": "unit", "output": output}

    monkeypatch.setattr(digital_twin_tools, "run_digital_twin_tool", fake_tool)

    status, reason = run(_asgi_json("GET", "/api/park/golden-incident/reason"))
    assert status == 200
    assert reason["mode"] == "backend_golden_reasoning_tournament"
    assert reason["selectedAction"]["id"] == "bounded_split_flow"
    assert reason["agentOpsLedger"]["recorded"] is True

    status, command = run(_asgi_json("GET", "/api/park/command-center"))
    assert status == 200
    assert command["mode"] == "unified_incident_command_center"
    assert command["caseFile"]["status"] == "active"
    assert command["linkedArtifacts"]["tickets"][0]["id"] == "ticket-1"

    status, decision = run(_asgi_json("POST", "/api/park/command-center/decision", {"decision_id": "dispatch_hold", "decision": "approved", "note": "unit"}))
    assert status == 200
    assert decision["resolvedDecision"]["decision"] == "approved"

    status, not_allowed = run(_asgi_json("POST", "/api/park/command-center"))
    assert status == 405
    assert not_allowed["status"] == "method_not_allowed"


def test_main_reasoning_and_delayed_outcome_payloads(monkeypatch, tmp_path):
    log_path = tmp_path / "reasoning.jsonl"
    delayed_path = tmp_path / "delayed.jsonl"
    monkeypatch.setenv("PARKPULSE_HEARTBEAT_OUTCOME_DELAY_SECONDS", "1")
    monkeypatch.setenv("PARKPULSE_HEARTBEAT_DELAYED_OUTCOME_LOG_PATH", str(delayed_path))
    monkeypatch.setenv("PARKPULSE_HEARTBEAT_ACTION_LOG_PATH", str(tmp_path / "heartbeat.jsonl"))
    monkeypatch.setenv("PARKPULSE_REASONING_TRAINING_AUDIT_LOG_PATH", str(log_path))

    entry = {
        "id": "action-1",
        "created_at": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "mode": "cached_post_trained_model_heartbeat_controller",
        "scenario_key": "food_spike",
        "candidate": {"target": "food", "action": "redirect_food_demand", "score": 88},
        "active_incidents": [{"kind": "food_pressure"}, {"kind": "queue_spillover"}],
        "episode_fitness": {
            "scores": {"actual": 84, "baseline": 71, "reward_delta": 13, "fitness": 86, "difficulty_adjusted_fitness": 83},
            "pressure": {"reduction_vs_baseline": 11, "reduced_pressure": 52},
        },
        "executed": True,
    }
    llm = {
        "interpretation": {
            "scenario_tags_for_review": ["food pressure", "invented private guest profile", "queue spillover"],
            "reward_metric_audit_questions": ["Does pressure fall after redirect?"],
            "feature_backlog": ["Add food queue spillover feature"],
            "diagnostic_summary": ["Food action matches observed pressure."],
            "mechanism_hypothesis": "Backlog moved to spare capacity.",
        }
    }
    audit = main._grounded_reasoning_training_audit(entry, llm, {"mechanism_ids": ["m-food"], "failure_hierarchy": ["queue"]})
    assert audit["accepted_feature_tags"] == ["food_pressure", "queue_spillover"]
    assert "invented_private_guest_profile" in audit["rejected_feature_tags"]
    assert audit["training_integration"]["excluded_from"] == ["reward", "training_label", "promotion_gate", "live_action"]

    written = main._write_reasoning_training_audit(audit)
    duplicate = main._write_reasoning_training_audit(audit)
    skipped = main._write_reasoning_training_audit({"mode": "wrong"})
    assert written["status"] == "written"
    assert duplicate["status"] == "unchanged"
    assert skipped["status"] == "skipped"

    matured = main._delayed_outcome_attribution_row(entry)
    pending_timestamp = main._delayed_outcome_attribution_row({**entry, "id": "action-2", "created_at": None})
    missing_measurement = main._delayed_outcome_attribution_row({**entry, "id": "action-3", "episode_fitness": {}})
    not_executed = main._delayed_outcome_attribution_row({**entry, "id": "action-4", "executed": False})
    assert matured["status"] == "matured"
    assert matured["training"]["eligible"] is True
    assert pending_timestamp["status"] == "pending_timestamp"
    assert missing_measurement["status"] == "missing_measurement"
    assert not_executed["status"] == "review_not_executed"

    monkeypatch.setattr(main, "_recent_jsonl_records", lambda path, limit=1000: [] if str(path) == str(delayed_path) else [entry])
    payload = main._delayed_outcome_attribution_payload(limit=5)
    assert payload["status"] == "ready"
    assert payload["summary"]["eligible_training_rows"] == 1
    assert payload["attribution_log"]["status"] == "written"


def test_main_counterfactual_policy_payloads(monkeypatch, tmp_path):
    action_record = {
        "id": "hb-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "cached_post_trained_model_heartbeat_controller",
        "scenario_key": "ride_down",
        "candidate": {"id": "ride_reroute", "target": "ride", "action": "reroute_down_ride", "expected_effect": "reduce queue pressure"},
        "active_incidents": [{"kind": "ride_sensor", "signalReliabilityPct": 45, "intensity": 82}],
        "candidate_scores": [{"id": "ride_reroute", "target": "ride", "action": "reroute_down_ride"}],
    }
    generated = {
        "changed_plan": True,
        "base_plan": {"step": "reroute guests"},
        "mutated_plan": {"step": "route sensor conflict through human review and verify evidence before dispatch and avoid reopening"},
        "change_summary": "Plan now asks a human to verify conflict and protects queue staging with observed evidence.",
        "uncertainty_handling": ["human review must verify sensor conflict"],
    }
    spec = {
        "mutation_type": "signal_conflict_intensified",
        "positive_terms": ["verify", "conflict", "sensor"],
        "negative_terms": ["trust sensor"],
        "expected_direction": "Increase verification.",
    }

    alignment = main._counterfactual_expected_alignment(spec, generated)
    traps = main._counterfactual_policy_trap_checks(action_record, spec, generated)
    failures = main._counterfactual_failure_modes(alignment, traps, generated)
    assert alignment["status"] == "pass"
    assert traps["status"] == "pass"
    assert failures == ["none_detected"]

    unsafe = main._counterfactual_policy_trap_checks(
        action_record,
        spec,
        {"mutated_plan": "reopen immediately in 5 minutes and auto dispatch staff without approval"},
    )
    assert unsafe["status"] == "fail"
    assert unsafe["critical_count"] >= 1

    async def fake_case(record, case_spec):
        return {
            "id": f"{record['id']}_{case_spec['mutation_type']}",
            "status": "pass",
            "scenario_key": record["scenario_key"],
            "mutation_type": case_spec["mutation_type"],
            "alignment": {"score": 0.92},
            "failure_modes": ["none_detected"],
            "policy_traps": {"traps": []},
        }

    monkeypatch.setattr(main, "_recent_jsonl_records", lambda path, limit=240: [action_record])
    monkeypatch.setattr(main, "_counterfactual_mutation_specs_for_record", lambda record: [spec, {**spec, "mutation_type": "crowd_wave_added"}])
    monkeypatch.setattr(main, "_run_counterfactual_mutation_case", fake_case)
    monkeypatch.setattr(main, "_write_counterfactual_mutation_rows", lambda cases: {"status": "written", "written_count": len(cases)})
    monkeypatch.setattr(main, "_counterfactual_mutation_mongo_status", lambda payload, persist: {"status": "skipped", "persist": persist})
    monkeypatch.setenv("PARKPULSE_COUNTERFACTUAL_MONGO_TIMEOUT_SECONDS", "0.5")

    payload = run(main._counterfactual_mutation_eval_payload(limit=10, persist_mongo=False))
    assert payload["status"] == "ready"
    assert payload["summary"]["case_count"] == 2
    assert payload["summary"]["pass_rate"] == 1.0
    assert payload["mutation_log"]["written_count"] == 2
    assert payload["mongo_memory"]["persist"] is False

    trap_rows = [
        {"status": "pass", "scenario_key": "ride_down", "mutation_type": "signal", "failure_modes": ["none_detected"], "policy_traps": {"critical_count": 0, "traps": []}},
        {"status": "fail", "scenario_key": "ride_down", "mutation_type": "unsafe", "failure_modes": ["unsafe_reopen"], "policy_traps": {"critical_count": 2, "traps": [{"id": "unsafe_reopen_without_safe_status"}]}},
        {"status": "review", "scenario_key": "food_spike", "mutation_type": "crowd", "failure_modes": ["weak_grounding"], "policy_traps": {"critical_count": 0, "traps": [{"id": "weak_grounding"}]}},
    ]
    monkeypatch.setattr(main, "_latest_counterfactual_mutation_rows", lambda limit=120: trap_rows)
    policy_payload = main._policy_trap_eval_payload(limit=50)
    assert policy_payload["status"] == "ready"
    assert policy_payload["summary"]["fail_count"] == 1
    assert policy_payload["summary"]["critical_trap_count"] == 2


def test_main_heartbeat_controller_review_and_execution(monkeypatch):
    class HeartbeatSimulation:
        async def get_state_lite(self):
            return {"simTime": {"minute": 10}, "guestFlow": {"activeScenario": {"key": "food_spike"}}, "chaosEngine": {"activeUnexpectedEvents": [{"kind": "food", "intensity": 70, "targetId": "foodCourt1"}]}}

    class ExecutingSimulation(HeartbeatSimulation):
        async def get_state_lite(self):
            return {"simTime": {"minute": 11}, "guestFlow": {"activeScenario": {"key": "food_spike"}}, "chaosEngine": {"activeUnexpectedEvents": [{"kind": "food", "intensity": 55, "targetId": "foodCourt1"}]}}

    async def fake_execute(target, action):
        return {
            "status": "success",
            "message": f"{target}:{action}",
            "episode_fitness": {
                "id": "episode-1",
                "scores": {"actual": 91, "baseline": 82, "reward_delta": 9, "fitness": 90},
                "pressure": {"reduction_vs_baseline": 8},
                "difficulty": {"level": "unit"},
            },
        }

    monkeypatch.setenv("PARKPULSE_HEARTBEAT_CONTROLLER_ENABLED", "true")
    monkeypatch.setenv("PARKPULSE_HEARTBEAT_MIN_ACTIVE_CHAOS", "1")
    monkeypatch.setenv("PARKPULSE_HEARTBEAT_ACTION_COOLDOWN_SECONDS", "1")
    monkeypatch.setattr(main, "_fast_park_simulation", HeartbeatSimulation())
    monkeypatch.setattr(main, "_heartbeat_controller_running", False)
    monkeypatch.setattr(main, "_heartbeat_controller_last_action_at", None)
    monkeypatch.setattr(main, "_heartbeat_policy_snapshot_for_tick", lambda: {"status": "ready", "sample_count": 40, "source": "unit"})
    monkeypatch.setattr(main, "_heartbeat_candidate_actions", lambda state, snapshot: [{"id": "staff", "target": "staff", "action": "redeploy_staff", "score": 80, "learned_q": 20, "learned_sample_count": 0, "scenario_key": "food_spike"}])
    logs = []
    monkeypatch.setattr(main, "_record_heartbeat_action_log", lambda entry: logs.append(entry))

    reviewed = run(main._maybe_run_heartbeat_controller(advanced_steps=1))
    assert reviewed["status"] == "review"
    assert reviewed["executed"] is False
    assert reviewed["delayed_outcome_attribution"]["status"] == "review_not_executed"
    assert logs[-1]["id"] == reviewed["id"]

    import park_simulation as park_simulation_module

    monkeypatch.setattr(main, "_fast_park_simulation", ExecutingSimulation())
    monkeypatch.setattr(main, "_heartbeat_controller_last_action_at", None)
    monkeypatch.setattr(
        main,
        "_heartbeat_candidate_actions",
        lambda state, snapshot: [{"id": "food", "target": "food", "action": "redirect_food_demand", "score": 72, "learned_q": 88, "learned_sample_count": 4, "scenario_key": "food_spike"}],
    )
    monkeypatch.setattr(main, "_heartbeat_policy_gate", lambda selected, state, snapshot: {"allowed": True, "gate_status": "allowed", "findings": ["unit allowed"]})
    monkeypatch.setattr(park_simulation_module.park_simulation, "execute_action", fake_execute)

    executed = run(main._maybe_run_heartbeat_controller(advanced_steps=1))
    assert executed["status"] == "success"
    assert executed["executed"] is True
    assert executed["result"]["message"] == "food:redirect_food_demand"
    assert executed["episode_fitness"]["id"] == "episode-1"

    monkeypatch.setattr(main, "_heartbeat_controller_running", True)
    assert run(main._maybe_run_heartbeat_controller(advanced_steps=1)) is None


def test_api_session_wrappers_hot_cache_and_customer_emergency(monkeypatch):
    monkeypatch.setattr(parkpulse_api, "evaluate_policy_action", lambda session_id, body: (_ for _ in ()).throw(KeyError("missing session")))
    with pytest.raises(parkpulse_api.HTTPException) as missing:
        run(parkpulse_api.park_agent_policy_check("session-x", {"action": "go"}))
    assert missing.value.status_code == 404

    monkeypatch.setattr(parkpulse_api, "evaluate_policy_action", lambda session_id, body: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(parkpulse_api.HTTPException) as denied:
        run(parkpulse_api.park_agent_policy_check("session-x", {"action": "go"}))
    assert denied.value.status_code == 403

    monitor_calls = []

    async def broken_lite():
        raise RuntimeError("lite unavailable")

    class BrokenLiteSimulation:
        get_state_lite = staticmethod(broken_lite)

    def fake_monitor(session_id, body, park_state=None):
        monitor_calls.append({"session_id": session_id, "body": body, "park_state": park_state})
        return {"status": "ok", "event": body["event"], "has_state": park_state is not None}

    monkeypatch.setattr(parkpulse_api, "park_simulation", BrokenLiteSimulation())
    monkeypatch.setattr(parkpulse_api, "monitor_session", fake_monitor)
    monitor = run(parkpulse_api.park_agent_monitor("session-1", {}))
    assert monitor == {"status": "ok", "event": "live", "has_state": False}
    assert monitor_calls[-1]["park_state"] is None

    async def builder():
        return {"status": "fresh"}

    parkpulse_api._hot_endpoint_refreshing.add("unit")
    run(parkpulse_api.refresh_hot_endpoint("unit", 5, builder))
    assert "unit" not in parkpulse_api._hot_endpoint_refreshing
    assert parkpulse_api._hot_endpoint_cache["unit"][1] == {"status": "fresh"}
    parkpulse_api._hot_endpoint_refreshing.add("unit-prewarm")
    run(parkpulse_api.prewarm_hot_endpoint("unit-prewarm", 5, builder))
    assert "unit-prewarm" not in parkpulse_api._hot_endpoint_refreshing

    monkeypatch.setenv("MONGODB_DISABLE_DRIVER_IMPORT", "false")
    monkeypatch.setattr(
        parkpulse_api,
        "get_latest_memory_documents",
        lambda collection, limit: [{"_id": "mongo-1", "status": "operator_review"}, {"_id": "mongo-2", "status": "resolved"}],
    )
    persisted = parkpulse_api._persisted_customer_emergency_incidents(limit=5, status="operator_review")
    assert persisted["source"] == "operational_memory"
    assert persisted["incidents"][0]["id"] == "mongo-1"
    assert persisted["summary"]["operator_review"] == 1

    monkeypatch.setattr(parkpulse_api, "get_latest_memory_documents", lambda collection, limit: [])
    monkeypatch.setattr(parkpulse_api, "list_customer_emergency_incidents", lambda limit=30, status=None: {"status": "ok", "source": "fallback", "incidents": []})
    assert parkpulse_api._persisted_customer_emergency_incidents()["source"] == "fallback"


def test_api_live_feed_delivery_and_simulated_impact(monkeypatch):
    monkeypatch.setattr(parkpulse_api, "delivery_outbox_status", lambda: {"status": "ok"})
    monkeypatch.setattr(
        parkpulse_api,
        "send_worker_notification",
        lambda payload: {"status": "delivered", "id": f"dispatch-{payload['sourceTool']}", "channel": "worker_device", "durable": True, "idempotencyKey": "idem-1"},
    )
    monkeypatch.setattr(
        parkpulse_api,
        "acknowledge_dispatch",
        lambda dispatch_id, actor, choice, channel: {"status": "acknowledged", "lastAcknowledgement": {"actor": actor}},
    )
    payload = {
        "decision_id": "decision-1",
        "live_feed_case": {"generated_issue": {"kind": "storm_risk", "targetId": "coveredPlaza"}, "live_feed_event_ids": ["event-1"]},
        "risk_escalated_tool_executor": {
            "receipts": [
                {
                    "agent": "tool",
                    "department": "operations",
                    "source_tool": "recommend_route_change",
                    "approval_id": "approval-1",
                    "policy_status": "approved",
                    "policy_check": {"status": "approved"},
                    "risk_escalation_approval": {"receiver": "ops_receiver", "lifted_scope": "route advisory", "rollback": "stop"},
                    "result": {"status": "executed_escalated_simulated", "idempotency_key": "idem-1", "rollback": "stop"},
                },
                {"agent": "tool", "department": "guest_care", "source_tool": "draft_guest_message", "result": {"status": "preview"}},
            ]
        },
    }
    proof = parkpulse_api._risk_escalation_receiver_delivery_proof(payload)
    assert proof["status"] == "proven_escalated"
    assert proof["delivered_count"] == 1
    assert proof["receipts"][1]["status"] == "not_dispatched_escalation_preview"

    assert "food court" in parkpulse_api._live_feed_controlled_impact_text("demand_spike", "food_retail", "inventory_alert", "foodCourt1")
    assert "worker break" in parkpulse_api._live_feed_controlled_impact_text("staff_callout", "hr_labor", "shift_adjustment_recommendation", "frontGate")
    assert "hvac" in parkpulse_api._live_feed_controlled_impact_text("storm_risk", "maintenance", "create_work_order", "shelter")
    assert "crowd security" in parkpulse_api._live_feed_controlled_impact_text("access_lane_block", "operations", "create_ops_alert", "gate")
    assert "food guest demand" in parkpulse_api._live_feed_controlled_impact_text("demand_spike", "marketing", "redirect_offer", "foodCourt1")

    async def fake_apply(dispatches, reason):
        return {
            "status": "success",
            "message": reason,
            "stateImpact": {"executed_tools": [row["payload"]["sourceTool"] for row in dispatches]},
            "episode_fitness": {"scores": {"fitness": 90, "reward_delta": 8}, "pressure": {"reduction_vs_baseline": 5}},
        }

    class ImpactSimulation:
        apply_delivery_outcomes = staticmethod(fake_apply)

    monkeypatch.setattr(parkpulse_api, "park_simulation", ImpactSimulation())
    monkeypatch.setattr(parkpulse_api, "clear_hot_endpoint_cache", lambda: None)
    controlled = run(
        parkpulse_api._apply_controlled_live_feed_simulated_ops_impact(
            {
                "live_feed_case": {"generated_issue": {"kind": "demand_spike", "targetId": "foodCourt1"}},
                "live_feed_receiver_delivery": {
                    "status": "proven_controlled",
                    "receipts": [
                        {"delivered": True, "acknowledged": True, "department": "food_retail", "source_tool": "inventory_alert", "receiver": "food", "dispatch_id": "d1"},
                        {"delivered": True, "acknowledged": True, "department": "hr_labor", "source_tool": "shift_adjustment_recommendation", "receiver": "hr", "dispatch_id": "d2"},
                    ],
                },
            }
        )
    )
    assert controlled["status"] == "applied"
    assert controlled["episode_fitness"]["fitness"] == 90
    assert controlled["episode_fitness"]["pressureReduction"] == 5

    skipped = run(parkpulse_api._apply_controlled_live_feed_simulated_ops_impact({"live_feed_receiver_delivery": {"status": "incomplete"}}))
    assert skipped["status"] == "skipped"


def test_api_copilot_gemini_branches_and_refinement(monkeypatch):
    import gemini_hard_timeout

    monkeypatch.setenv("PARKPULSE_COPILOT_HOT_PATH_LOCAL_ONLY", "false")
    monkeypatch.setenv("PARKPULSE_COPILOT_LLM_FOR_ALL_TURNS", "true")
    monkeypatch.setattr(parkpulse_api, "get_gemini_agent_properties", lambda: SimpleNamespace(ready=True, platform="unit", model="gemini-unit", readiness_issues=[]))

    async def fake_gemini(prompt, **kwargs):
        required = prompt.get("required_json", {})
        if "intent" in required:
            return {
                "transport": "unit-transport",
                "text": json.dumps(
                    {
                        "intent": "revise_plan",
                        "understood_question": "tighten the plan",
                        "constraints": ["no public message"],
                        "relevant_park_facts": ["food queue high"],
                        "answer_type": "action",
                        "action_needed": True,
                        "planner_message": "Revise without public messaging.",
                        "confidence": 93,
                    }
                ),
            }
        if "answer" in required:
            return {"transport": "unit-transport", "text": json.dumps({"answer": "I will keep this bounded.", "reasoning_bullets": ["Policy gate is clean."], "operator_next": "Approve", "confidence": 91})}
        return {"transport": "unit-transport", "text": json.dumps({"status": "refined", "headline": "Refined", "operator_brief": "Tighter action.", "refined_actions": ["hold public message"], "policy_notes": ["bounded"], "confidence": 0.9})}

    monkeypatch.setattr(gemini_hard_timeout, "generate_gemini_json_hard_timeout", fake_gemini)
    brain = run(parkpulse_api._copilot_chat_brain("tighten the plan", {"primary": "food"}, {"agent_runtime": {"id": "prior"}}, []))
    assert brain["source"] == "gemini_chat_brain"
    assert brain["intent"] == "revise_plan"
    assert brain["constraints"] == ["no public message"]

    response = run(
        parkpulse_api._copilot_conversational_response(
            "say it tighter",
            base_answer="Local answer",
            compact_state={"primary": "food"},
            route={"selected_role": "react", "policy_gates": ["bounded"]},
            intent={"asks_action": True},
            object_action_plan={"selected_action": {"label": "Hold"}},
            reasoning_evaluation={"overall": 82},
            agent_runtime={"status": "prepared", "summary": "ready"},
            map_grounding={"status": "ready"},
            impact_replay={"executed": False, "comparison": {"impact": {"headline": "No mutation"}}},
            clarifying_question=None,
            prior_copilot=None,
            semantic_memory_context={"status": "ready"},
            mode="propose",
        )
    )
    assert response["source"] == "gemini_conversation"
    assert response["answer"] == "I will keep this bounded."

    refine = run(
        parkpulse_api.park_agent_role_refine(
            parkpulse_api.AgentRoleRefineRequest(
                message="refine",
                receipt={"selected_role": "react", "role_receipt": {"scenario_key": "food_spike"}, "run_telemetry": {"delivery": {"dispatches": [{"channel": "worker", "status": "queued"}]}}},
            )
        )
    )
    assert refine["status"] == "complete"
    assert refine["refinement"]["headline"] == "Refined"

    async def broken_gemini(prompt, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(gemini_hard_timeout, "generate_gemini_json_hard_timeout", broken_gemini)
    fallback_brain = run(parkpulse_api._copilot_chat_brain("what now", {}, None, []))
    fallback_response = run(
        parkpulse_api._copilot_conversational_response(
            "what now",
            base_answer="Local answer",
            compact_state={},
            route={},
            intent={},
            object_action_plan=None,
            reasoning_evaluation=None,
            agent_runtime=None,
            map_grounding=None,
            impact_replay=None,
            clarifying_question=None,
            prior_copilot=None,
            semantic_memory_context=None,
            mode="answer",
        )
    )
    fallback_refine = run(parkpulse_api.park_agent_role_refine(parkpulse_api.AgentRoleRefineRequest(message="refine", receipt={})))
    assert fallback_brain["source"] == "local_intent_parser_llm_unavailable"
    assert fallback_response["source"] == "local_runtime_response"
    assert fallback_refine["status"] == "fallback"


def test_main_evidence_heartbeat_and_monitor_helper_gaps(monkeypatch, tmp_path):
    persisted_jobs = []
    monkeypatch.setattr(main, "_persist_evidence_refresh_job", lambda job: persisted_jobs.append(dict(job)))
    main._evidence_refresh_jobs.clear()
    main._evidence_endpoint_cache.clear()

    async def builder_ok():
        return {"status": "ready", "mode": "unit_builder", "value": 1}

    async def builder_fail():
        raise RuntimeError("builder failed")

    job_id = main._evidence_refresh_job_id("unit-cache")
    main._evidence_refresh_jobs[job_id] = {"id": job_id, "status": "queued", "cache_key": "unit-cache"}
    run(main._run_evidence_refresh_job(job_id, "unit-cache", 10, builder_ok))
    assert main._evidence_refresh_jobs[job_id]["status"] == "completed"
    assert main._evidence_cached_payload("unit-cache")["evidence_cache"]["state"] == "fresh"

    fail_id = main._evidence_refresh_job_id("unit-cache-fail")
    main._evidence_refresh_jobs[fail_id] = {"id": fail_id, "status": "queued", "cache_key": "unit-cache-fail"}
    run(main._run_evidence_refresh_job(fail_id, "unit-cache-fail", 10, builder_fail))
    assert main._evidence_refresh_jobs[fail_id]["status"] == "failed"
    assert "builder failed" in main._evidence_refresh_jobs[fail_id]["error"]

    created_tasks = []

    def fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(main.asyncio, "create_task", fake_create_task)
    queued = main._evidence_refresh_accepted_payload("monitor", "unit-cache-queued", 5, builder_ok)
    duplicate = main._start_evidence_refresh_job("monitor", "unit-cache-queued", 5, builder_ok)
    assert queued["status"] == "refresh_queued"
    assert duplicate["status"] == "queued"
    assert created_tasks

    state = {"chaosEngine": {"activeUnexpectedEvents": [{"kind": "food", "intensity": 50}]}}
    safe_candidate = {"target": "food", "action": "redirect_food_demand", "score": 80}
    ready_snapshot = {"status": "ready", "sample_count": 50}
    assert main._safe_auto_execute_lane(safe_candidate, state, ready_snapshot)["allowed"] is True
    monkeypatch.setenv("PARKPULSE_ENABLE_SAFE_AUTO_EXECUTE", "false")
    assert main._safe_auto_execute_lane(safe_candidate, state, ready_snapshot)["allowed"] is False
    monkeypatch.setenv("PARKPULSE_ENABLE_SAFE_AUTO_EXECUTE", "true")
    assert main._safe_auto_execute_lane({"target": "ride", "action": "reroute_down_ride", "score": 80}, state, ready_snapshot)["allowed"] is False
    assert main._safe_auto_execute_lane(safe_candidate, state, {"status": "ready", "sample_count": 1})["allowed"] is False
    assert main._safe_auto_execute_lane({**safe_candidate, "slice_gate": {"status": "slice_hold", "reason": "thin data", "slice": {"decision": "hold_slice"}}}, state, ready_snapshot)["allowed"] is False
    assert main._safe_auto_execute_lane({**safe_candidate, "score": 1}, state, ready_snapshot)["allowed"] is False

    now = datetime.now(timezone.utc)
    current = {
        "id": "hb-current",
        "created_at": now.isoformat(),
        "scenario_key": "food_spike",
        "candidate": {"target": "food", "action": "redirect_food_demand", "score": 88, "expected_effect": "food queue relief"},
        "policy_gate": {"allowed": True},
        "active_incidents": [{"kind": "food_queue", "intensity": 70}],
        "candidate_scores": [
            {"id": "food", "target": "food", "action": "redirect_food_demand", "score": 88},
            {"id": "crowd", "target": "crowd_safety", "action": "calm_reroute", "score": 86, "expected_effect": "spread crowd"},
        ],
        "episode_fitness": {"scores": {"reward_delta": 8}, "pressure": {"reduction_vs_baseline": 5}},
        "executed": True,
    }
    prior_positive = {**current, "id": "hb-prior", "created_at": (now - timedelta(minutes=5)).isoformat()}
    prior_regression = {
        **current,
        "id": "hb-regression",
        "created_at": (now - timedelta(minutes=4)).isoformat(),
        "episode_fitness": {"scores": {"reward_delta": -3}, "pressure": {"reduction_vs_baseline": -2}},
    }
    priors = main._heartbeat_prior_outcome_evidence(current, [current, prior_positive, prior_regression])
    alternatives = main._heartbeat_top_alternatives(current)
    assert priors["match_count"] == 2
    assert priors["positive_count"] == 1
    assert priors["regression_count"] == 1
    assert alternatives[0]["id"] == "crowd"
    assert main._heartbeat_failure_class({**current, "policy_gate": {"allowed": False}}, {"label": "positive"}, priors, alternatives) == "policy_gate_review_or_block"
    assert main._heartbeat_failure_class(current, {"label": "regression"}, priors, alternatives) == "wrong_lever"

    mechanisms = main._causal_mechanism_library(
        {
            "candidate": {"target": "food", "action": "redirect_food_demand"},
            "active_incidents": [
                {"kind": "ride_failure", "detail": "ride queue spill into food"},
                {"kind": "parade_route_conflict"},
                {"kind": "storm_energy_hvac", "intensity": 91},
            ],
        },
        {"failure_class": "policy_gate_too_permissive", "label": "regression", "incident_summary": {"max_intensity": 91}},
    )
    mechanism_ids = {item["id"] for item in mechanisms}
    assert {"ride_failure_to_food_or_crowd_spillover", "parade_conflict_blocks_reroute", "high_chaos_needs_combined_lever", "energy_or_weather_constrains_equipment", "policy_gate_too_permissive"} <= mechanism_ids

    async def fake_fast_case_index():
        return {
            "status": "ready",
            "rows": [
                {
                    "id": "case-food",
                    "title": "Food queue pressure",
                    "domain": "food",
                    "severity": "high",
                    "priority": {"rationale": "food queue"},
                }
            ],
        }

    monkeypatch.setattr(main, "_fast_case_index", fake_fast_case_index)
    monkeypatch.setattr(
        agent_ops_ledger,
        "read_agent_ops_ledger",
        lambda limit=80, q=None, **kwargs: {
            "status": "ready",
            "items": [
                {
                    "id": "receipt-1",
                    "caseId": "case-food",
                    "traceId": "trace-1",
                    "policyRefs": ["P-food"],
                    "receiverActions": ["food_receiver"],
                    "outcomeEvidence": {"status": "measured"},
                    "dispatchCount": 2,
                    "evalScore": 91,
                    "gate": "passed",
                    "summary": "Food queue relief",
                }
            ],
        },
    )
    monkeypatch.setattr(
        main,
        "review_training_ledger",
        lambda limit=80: {"status": "ready", "open_reviews": [{"id": "review-1", "case_id": "case-food", "status": "open", "reason": "food queue"}]},
    )
    monkeypatch.setattr(
        main,
        "_fast_operational_doctrine_index",
        lambda: {"status": "ready", "policy_refs": [{"policy_ref": "P-food", "title": "Food policy", "summary": "bounded food action"}], "action_cases": [{"id": "policy-case", "policy_refs": ["P-food"], "title": "Food queue pressure"}]},
    )
    monkeypatch.setattr(main, "_policy_ref_detail", lambda ref_id: {"matches": [{"title": "Food policy", "allowed_action": "bounded food action", "condition": "food queue"}]})
    monkeypatch.setattr(main, "_monitor_source_watermark", lambda: {"status": "unit"})

    graph = run(main._monitor_evidence_graph(limit=5))
    assert graph["status"] == "ready"
    assert graph["summary"]["trace_record_count"] == 1
    assert graph["cases"][0]["outcome_evidence"]["status"] == "measured_receipt"
    assert graph["cases"][0]["trace_records"][0]["policy_ref_rows"][0]["policy_ref"] == "P-food"


def test_main_live_episode_export_policy_gate_understanding_and_runtime_success(monkeypatch):
    class EpisodeSimulation:
        async def get_episode_fitness(self, limit=80):
            return {
                "episodes": [
                    "ignore",
                    {
                        "id": "episode-1",
                        "scenario_key": "food_spike",
                        "scores": {"fitness": 87, "difficulty_adjusted_fitness": 83, "reward_delta": 12},
                        "pressure": {"reduction_vs_baseline": 9, "reduced_pressure": 41},
                        "difficulty": {"score": 77, "active_random_incident_count": 2},
                        "active_random_incidents": [{"kind": "food_queue"}, {"kind": "staff_shortage"}],
                        "action": {"target": "food", "action": "redirect_food_demand"},
                    },
                    {
                        "id": "episode-2",
                        "scenario_key": "ride_down",
                        "scores": {"fitness": 40, "reward_delta": -5},
                        "pressure": {"reduction_vs_baseline": -3},
                        "difficulty": {},
                        "active_random_incidents": [],
                        "action": {"target": "ride", "action": "reroute_down_ride"},
                    },
                ]
            }

    built_rows = []

    def fake_build_analytics_rows(**kwargs):
        built_rows.append(kwargs)
        return {
            "outcome_events": [{"decision_id": kwargs["decision_id"], "source": kwargs["source"]}],
            "action_dispatches": [{"decision_id": kwargs["decision_id"]}],
            "eval_results": [{"decision_id": kwargs["decision_id"], "overall": kwargs["eval_result"]["overall"]}],
        }

    def fake_export(rows_by_table):
        return {"status": "exported", "row_counts": {table: len(rows) for table, rows in rows_by_table.items()}}

    monkeypatch.setattr(main, "_fast_park_simulation", EpisodeSimulation())
    monkeypatch.setattr(main, "_exported_episode_fitness_ids", set())
    monkeypatch.setitem(sys.modules, "bigquery_analytics", SimpleNamespace(build_analytics_rows=fake_build_analytics_rows, export_analytics_rows=fake_export))
    export = run(main._export_live_episode_fitness_to_bigquery(limit=5))
    assert export["status"] == "exported"
    assert export["episode_ids"] == ["episode-2", "episode-1"]
    assert export["row_counts"]["outcome_events"] == 2
    assert built_rows[0]["eval_result"]["scorecard"]["status"] == "review"
    no_new = run(main._export_live_episode_fitness_to_bigquery(limit=5))
    assert no_new["status"] == "no_new_rows"

    candidate = {
        "target": "food",
        "action": "redirect_food_demand",
        "score": 77,
        "learned_q": 81,
        "learned_sample_count": 5,
        "slice_gate": {"status": "slice_promotable", "reason": "slice passed"},
    }
    state = {"chaosEngine": {"activeUnexpectedEvents": [{"kind": "food", "intensity": 40}]}}
    snapshot = {
        "status": "ready",
        "sample_count": 90,
        "model_ops": {"promotion_gate": {"status": "slice_promotable", "decision": "promote_slice", "warnings": ["watch drift"], "blockers": []}, "version": {"id": "v1"}},
    }
    allowed_gate = {"allowed": True, "gate_status": "allowed", "findings": ["fresh"]}
    monkeypatch.setattr(main, "live_weather_policy_gate", lambda candidate, state=None: allowed_gate)
    monkeypatch.setattr(main, "live_ride_ops_policy_gate", lambda candidate, state=None: allowed_gate)
    monkeypatch.setattr(main, "live_guest_flow_policy_gate", lambda candidate, state=None: allowed_gate)
    monkeypatch.setattr(main, "live_staffing_policy_gate", lambda candidate, state=None: allowed_gate)
    monkeypatch.setattr(main, "live_food_ops_policy_gate", lambda candidate, state=None: allowed_gate)
    monkeypatch.setattr(main, "live_operator_signal_policy_gate", lambda candidate, state=None: allowed_gate)
    gate = main._heartbeat_policy_gate(candidate, state, snapshot)
    assert gate["allowed"] is True
    assert gate["gate_status"] == "safe_auto_execute"
    assert gate["safe_auto_execute"]["lane"] == "safe_reversible_learning"

    non_safe = main._heartbeat_policy_gate({**candidate, "target": "staff", "action": "redeploy_staff"}, state, snapshot)
    assert non_safe["allowed"] is True
    assert non_safe["gate_status"] == "allowed"
    assert non_safe["promotion_gate"]["version"] == "v1"

    records = [
        {"id": "r1", "created_at": "2026-06-05T00:00:00Z", "scenario_key": "food_spike", "active_incidents": [{"kind": "food"}, {"kind": "staff"}]},
        {"id": "r2", "created_at": "2026-06-05T00:01:00Z", "scenario_key": "ride_down", "active_incidents": [{"kind": "food"}, {"kind": "staff"}]},
        {"id": "r3", "created_at": "2026-06-05T00:02:00Z", "scenario_key": "food_spike", "active_incidents": [{"kind": "storm"}, {"kind": "food"}]},
    ]
    edges = main._park_understanding_edges(records)
    assert any(edge["type"] == "scenario_transition" and edge["from"] == "food_spike" and edge["to"] == "ride_down" for edge in edges)
    assert any(edge["type"] == "incident_co_occurrence" and edge["from"] == "food" and edge["to"] == "staff" for edge in edges)

    view = main._mutation_record_view(
        {
            "id": "hb-1",
            "scenario_key": "ride_down",
            "candidate": {"target": "ride", "action": "reroute_down_ride"},
            "policy_gate": {"allowed": False, "gate_status": "review"},
            "active_incidents": [{"kind": "ride_sensor", "signalReliabilityPct": 55}],
        }
    )
    assert view["action_id"] == "hb-1"
    assert view["candidate"]["target"] == "ride"
    assert view["policy_gate"]["gate_status"] == "review"

    monkeypatch.setattr(main, "_recent_jsonl_records", lambda path, limit=240: records if "heartbeat" in str(path) else [{"id": "rollback-1"}])
    monkeypatch.setattr(main, "_delayed_outcome_attribution_payload", lambda limit=160: {"rows": [{"source_action_id": "r1", "status": "matured", "outcome": {"label": "positive", "scores": {"reward_delta": 4}, "pressure": {"reduction_vs_baseline": 3}}}]})
    monkeypatch.setattr(main, "_causal_reasoning_memory_payload", lambda limit=120: {"rows": [{"source_action_id": "r1", "mechanisms": [{"id": "food_spillover"}], "failure_class": "positive_single_observation"}]})
    artifact = main._park_understanding_memory_artifact(limit=30)
    assert artifact["status"] == "ready"
    assert artifact["summary"]["scenario_count"] >= 2
    assert artifact["park_dynamics_graph"]["edges"]

    context = {
        "live_state": {"scenario": {"key": "food_spike"}, "active_incidents": [{"kind": "food_queue", "visibility": "partial"}]},
        "latest_action": {"status": "review", "executed": False, "candidate": {"target": "food", "action": "redirect_food_demand"}, "policy_gate": {"gate_status": "review", "allowed": False, "findings": ["needs operator"]}},
        "park_understanding_score": {"score": 72, "grade": "B", "evidence_confidence": 0.7, "evidence_caps": {"executed_actions_in_window": 0}},
        "retrieval_quality": {"miss_count": 2},
        "policy_traps": {"summary": {"critical_trap_count": 1}},
        "delayed_outcomes": {"summary": {"eligible_training_rows": 1}},
    }
    blocked_answer = main._structured_ops_chat_answer("dispatch it", context, blocked="dispatch")
    hello_answer = main._structured_ops_chat_answer("hi", context, llm_issue="offline")
    followup_answer = main._structured_ops_chat_answer("explain like shift lead", context, history_context={"is_followup": True})
    assert blocked_answer["headline"] == "I cannot take that authority."
    assert hello_answer["headline"] == "Ops chat online"
    assert followup_answer["headline"] == "Plain-English read"

    class FullRuntimeModule:
        class OperatorCommandRequest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class ParkAgentRunRequest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        async def park_operator_command(self, request):
            return {"status": "full_operator", "request": request.kwargs}

        async def park_agent_run(self, request):
            return {"status": "full_agent", "run_telemetry": {"planner": {"selected_action": {"id": "food"}}}, "request": request.kwargs}

    full_module = FullRuntimeModule()
    async def fake_full_module(timeout):
        return full_module

    monkeypatch.setattr(main, "_parkpulse_app", None)
    monkeypatch.setattr(main, "_get_full_module_for_first_response", fake_full_module)
    monkeypatch.setattr(main, "_store_run_receipt", lambda payload, **kwargs: {**payload, "run_receipt": {"id": "receipt-1", "kind": kwargs.get("kind")}})
    monkeypatch.setattr(main, "_metric", lambda name: None)
    monkeypatch.setattr(main, "_full_runtime_status", lambda: {"loaded": True})
    monkeypatch.setattr(main, "live_weather_state_evidence", lambda: {"status": "ready"})
    monkeypatch.setattr(main, "live_ride_ops_state_evidence", lambda: {"status": "ready"})
    monkeypatch.setattr(main, "live_guest_flow_state_evidence", lambda: {"status": "ready"})
    monkeypatch.setattr(main, "live_staffing_state_evidence", lambda: {"status": "ready"})
    monkeypatch.setattr(main, "live_food_ops_state_evidence", lambda: {"status": "ready"})
    monkeypatch.setattr(main, "live_operator_signal_state_evidence", lambda: {"status": "ready"})
    monkeypatch.setattr(main, "live_weather_training_gate", lambda: {"allowed": True})
    monkeypatch.setattr(main, "live_ride_ops_training_gate", lambda: {"allowed": True})
    monkeypatch.setattr(main, "live_guest_flow_training_gate", lambda: {"allowed": True})
    monkeypatch.setattr(main, "live_staffing_training_gate", lambda: {"allowed": True})
    monkeypatch.setattr(main, "live_food_ops_training_gate", lambda: {"allowed": True})
    monkeypatch.setattr(main, "live_operator_signal_training_gate", lambda: {"allowed": True})
    monkeypatch.setattr(main, "_attach_live_weather_gate_to_payload", lambda payload: payload)

    operator_payload = run(main._build_operator_payload_with_runtime("status", "auto", False, "unit"))
    agent_payload = run(main._build_agent_run_payload_with_runtime({"scenario_key": "food_spike", "operator_message": "run it", "execute": False}, "unit"))
    assert operator_payload["status"] == "full_operator"
    assert operator_payload["run_receipt"]["kind"] == "operator_command"
    assert agent_payload["status"] == "full_agent"
    assert agent_payload["runtime_proof"]["full_runtime"]["loaded"] is True


def test_main_understanding_score_and_live_feed_route_wrappers(monkeypatch):
    mutation_rows = [
        {"status": "pass", "scenario_key": "food_spike"},
        {"status": "fail", "scenario_key": "ride_down"},
        {"status": "review", "scenario_key": "storm_response"},
    ]
    monkeypatch.setattr(main, "_latest_counterfactual_mutation_rows", lambda limit=240: mutation_rows)
    artifact = {
        "summary": {"heartbeat_records": 12, "scenario_count": 3, "causal_memory_rows": 2, "delayed_outcome_rows": 4, "top_mechanisms": [{"key": "food_spillover", "count": 2}]},
        "park_dynamics_graph": {
            "nodes": [
                {
                    "scenario_key": "food_spike",
                    "heartbeat_count": 5,
                    "executed_count": 3,
                    "review_count": 1,
                    "top_incidents": [{"key": "food", "count": 4}],
                    "top_actions": [{"key": "food/redirect", "count": 3}],
                    "top_mechanisms": [{"key": "food_spillover", "count": 2}],
                    "top_failure_classes": [{"key": "positive_single_observation", "count": 2}],
                    "evidence_action_ids": ["a1", "a2", "a3", "a4"],
                },
                {
                    "scenario_key": "ride_down",
                    "heartbeat_count": 3,
                    "executed_count": 0,
                    "review_count": 2,
                    "top_incidents": [{"key": "ride", "count": 2}],
                    "top_actions": [{"key": "ride/reroute", "count": 1}],
                    "top_mechanisms": [],
                    "top_failure_classes": [],
                    "evidence_action_ids": ["b1"],
                },
            ],
            "edges": [{"type": "scenario_transition"}, {"type": "incident_co_occurrence"}],
        },
        "llm": {
            "status": "ready",
            "interpretation": {
                "missing_state_features": ["capacity"],
                "cross_scenario_mechanisms": ["food to crowd"],
                "scenario_clusters": ["food"],
                "curriculum_items": ["explain gate"],
                "must_not_affect": ["live_action", "reward", "training_label", "promotion_gate", "rollback"],
            },
        },
        "offline_feature_backlog": [{"scenario_key": "ride_down"}],
    }
    score = main._park_understanding_score_artifact(artifact)
    assert score["status"] == "ready"
    assert score["mutation_consistency"]["passed"] == 1
    assert score["mutation_consistency"]["failed"] == 1
    assert score["dimensions"]["state_comprehension"]["score"] >= 1
    assert "some_scenario_profiles_missing_causal_mechanisms" in score["deterministic_checks"]["missed_facts"]

    async def allow(*args, **kwargs):
        return True

    async def fake_advance():
        return None

    class FeedSimulation:
        async def get_state_lite(self):
            return compact_state()

    monkeypatch.setattr(main, "_authorize_or_send", allow)
    monkeypatch.setattr(main, "_fast_park_simulation", FeedSimulation())
    monkeypatch.setattr(main, "_advance_fast_park_from_wall_clock", fake_advance)
    monkeypatch.setattr(main, "_invalidate_live_feed_health_cache", lambda: None)
    monkeypatch.setattr(main, "staffing_feed_config", lambda: {"feed": "staffing"})
    monkeypatch.setattr(main, "food_ops_feed_config", lambda: {"feed": "food"})
    monkeypatch.setattr(main, "operator_signal_feed_config", lambda: {"feed": "signal"})
    monkeypatch.setattr(main, "ride_ops_feed_config", lambda: {"feed": "ride"})
    monkeypatch.setattr(main, "guest_flow_feed_config", lambda: {"feed": "guest"})
    monkeypatch.setattr(main, "ingest_live_staffing_feed", lambda state: {"status": "loaded", "mode": "staffing"})
    monkeypatch.setattr(main, "ingest_live_food_ops_feed", lambda state: {"status": "loaded", "mode": "food"})
    monkeypatch.setattr(main, "ingest_live_operator_signal_feed", lambda state: {"status": "loaded", "mode": "signal"})
    monkeypatch.setattr(main, "ingest_live_ride_ops_feed", lambda state: {"status": "loaded", "mode": "ride"})
    monkeypatch.setattr(main, "ingest_live_guest_flow_feed", lambda state: {"status": "loaded", "mode": "guest"})

    status, staffing_config = run(_asgi_json("GET", "/api/park/live-feeds/staffing"))
    status_load, staffing_load = run(_asgi_json("POST", "/api/park/live-feeds/staffing/load", {}))
    _, ride_load = run(_asgi_json("POST", "/api/park/live-feeds/ride-ops/load", {}))
    _, guest_load = run(_asgi_json("POST", "/api/park/live-feeds/guest-flow/load", {}))
    assert status == 200
    assert staffing_config["mode"] == "live_staffing_feed_config"
    assert status_load == 200
    assert staffing_load["mode"] == "staffing"
    assert ride_load["mode"] == "ride"
    assert guest_load["mode"] == "guest"

    async def no_state():
        raise RuntimeError("feed state unavailable")

    monkeypatch.setattr(main, "_advance_fast_park_from_wall_clock", no_state)
    _, failed_food = run(_asgi_json("POST", "/api/park/live-feeds/food-ops/load", {}))
    assert failed_food["status"] == "error"
    assert failed_food["mode"] == "live_food_ops_feed_load"

    monkeypatch.setattr(main, "get_agent_onboarding", lambda agent_id: {"status": "ready", "agent_id": agent_id})
    monkeypatch.setattr(main, "certify_agent_onboarding", lambda agent_id, payload, park_state=None: {"status": "certified", "agent_id": agent_id, "has_state": park_state is not None})
    monkeypatch.setattr(main, "_fast_park_state_lite", FeedSimulation().get_state_lite)
    _, onboarding = run(_asgi_json("GET", "/api/park/agent-onboarding/unit-agent"))
    _, certified = run(_asgi_json("POST", "/api/park/agent-onboarding/unit-agent/certify", {"score": 1}))
    assert onboarding["agent_id"] == "unit-agent"
    assert certified["status"] == "certified"


def test_main_outcome_error_causal_audit_and_ops_chat_helpers(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_HEARTBEAT_OUTCOME_DELAY_SECONDS", "0")
    monkeypatch.setenv("PARKPULSE_OUTCOME_ERROR_LEDGER_PATH", str(tmp_path / "outcomes.jsonl"))
    monkeypatch.setenv("PARKPULSE_REASONING_TRAINING_AUDIT_LOG_PATH", str(tmp_path / "reasoning.jsonl"))
    created = datetime.now(timezone.utc).isoformat()
    current = {
        "id": "hb-outcome-1",
        "created_at": created,
        "mode": "cached_post_trained_model_heartbeat_controller",
        "scenario_key": "ride_down",
        "sim_time": {"minute": 10},
        "candidate": {"id": "ride", "target": "ride", "action": "reroute_down_ride", "score": 78, "learned_q": 75, "learned_sample_count": 4, "expected_effect": "queue relief"},
        "candidate_scores": [
            {"id": "ride", "target": "ride", "action": "reroute_down_ride", "score": 78},
            {"id": "food", "target": "food", "action": "redirect_food_demand", "score": 77},
        ],
        "policy_gate": {"allowed": True, "gate_status": "allowed", "findings": ["bounded"]},
        "active_incidents": [{"kind": "ride_failure_queue", "intensity": 72}],
        "episode_fitness": {"scores": {"fitness": 45, "reward_delta": -6}, "pressure": {"reduction_vs_baseline": -2}},
        "executed": True,
    }
    prior = {
        **current,
        "id": "hb-outcome-0",
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "episode_fitness": {"scores": {"fitness": 81, "reward_delta": 7}, "pressure": {"reduction_vs_baseline": 5}},
    }
    records = [current, prior]
    audit_row = {
        "id": "audit-1",
        "source_action_id": "hb-outcome-1",
        "accepted_feature_tags": ["ride_failure", "queue_relief"],
        "rejected_feature_tags": ["invented_profile"],
        "reward_metric_audit_questions": ["Did queue pressure fall?"],
        "feature_backlog": ["Separate ride queue spillover"],
    }

    def fake_recent(path, limit=1000):
        path_text = str(path)
        if "reasoning" in path_text:
            return [audit_row]
        if "outcomes" in path_text:
            return []
        return records

    monkeypatch.setattr(main, "_recent_jsonl_records", fake_recent)
    row = main._outcome_error_ledger_row(current, records)
    assert row["failure_class"] == "wrong_lever"
    assert row["label"] == "regression"
    assert row["training"]["eligible"] is True
    assert row["promotion_impact"] in {"reduce_weight", "hold_promotion", "blocks", "none"}

    payload = main._outcome_error_ledger_payload(limit=5)
    assert payload["status"] == "ready"
    assert payload["summary"]["row_count"] == 2
    assert payload["ledger_log"]["status"] == "written"

    mechanisms = [{"id": "ride_failure_to_food_or_crowd_spillover"}, {"id": "queue_relief"}]
    quality = main._audit_quality_for_action(current, mechanisms)
    hierarchy = main._failure_hierarchy(row, mechanisms)
    assert quality["status"] == "ready"
    assert quality["audit_id"] == "audit-1"
    assert "wrong_lever" in hierarchy

    history = [
        {"role": "assistant", "content": "Previous answer"},
        {"role": "user", "content": "Why is the ride down?"},
        {"role": "assistant", "content": "Because maintenance is holding it."},
    ]
    recent = main._ops_chat_recent_history(history)
    assert recent["has_history"] is True
    assert recent["last_user"] == "Why is the ride down?"
    assert main._ops_chat_is_followup("why?", history) is True
    assert main._ops_chat_effective_tool_message("what changed", history).startswith("Why is the ride down?")
    assert main._ops_chat_incident_phrase([{"kind": "storm", "targetId": "gate", "intensity": 80, "signalReliabilityPct": 60}]).startswith("storm at gate")


def test_main_refinement_workers_and_api_state_builders(monkeypatch):
    events = []
    monkeypatch.setattr(main, "_metric", lambda name: events.append(("metric", name)))
    monkeypatch.setattr(main, "_mark_receipt_upgrade_status", lambda receipt_id, status, payload: events.append(("mark", receipt_id, status, payload.get("mode"))))
    monkeypatch.setattr(main, "_upgrade_run_receipt", lambda receipt_id, payload, **kwargs: events.append(("upgrade", receipt_id, payload["status"], kwargs.get("kind"))))
    monkeypatch.setattr(main, "_release_refinement_slot", lambda receipt_id: events.append(("release", receipt_id)))
    monkeypatch.setattr(main, "_full_runtime_status", lambda: {"loaded": True})
    monkeypatch.setattr(main, "_timeout_tiers", lambda: {"refinement_seconds": 1})

    class RuntimeModule:
        class OperatorCommandRequest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class ParkAgentRunRequest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        async def park_operator_command(self, request):
            return {"status": "operator_refined", "request": request.kwargs}

        async def park_agent_run(self, request):
            return {"status": "agent_refined", "request": request.kwargs}

    runtime = RuntimeModule()
    monkeypatch.setattr(main, "_load_full_module_locked", lambda: runtime)
    main._operator_command_refinement_worker("status", "auto", False, "receipt-op")
    main._agent_run_refinement_worker({"scenario_key": "food_spike", "operator_message": "run", "execute": False}, "receipt-agent", "run", "food_spike")
    assert ("upgrade", "receipt-op", "operator_refined", "operator_command") in events
    assert ("upgrade", "receipt-agent", "agent_refined", "agent_run") in events

    class BrokenRuntime(RuntimeModule):
        async def park_operator_command(self, request):
            return "not a dict"

        async def park_agent_run(self, request):
            raise RuntimeError("agent failed")

    monkeypatch.setattr(main, "_load_full_module_locked", lambda: BrokenRuntime())
    main._operator_command_refinement_worker("status", "auto", False, "receipt-op-fail")
    main._agent_run_refinement_worker({"scenario_key": "ride_down"}, "receipt-agent-fail", "run", "ride_down")
    assert any(item[:3] == ("mark", "receipt-op-fail", "failed") for item in events)
    assert any(item[:3] == ("mark", "receipt-agent-fail", "failed") for item in events)

    submit_calls = []
    monkeypatch.setattr(main, "_try_claim_refinement_slot", lambda receipt_id: (False, "busy"))
    main._schedule_operator_command_refinement("status", "auto", False, "receipt-deferred")
    main._schedule_agent_run_refinement({"scenario_key": "food_spike"}, "receipt-agent-deferred", message="run", mode="food_spike")
    assert any(item[:3] == ("mark", "receipt-deferred", "deferred") for item in events)
    assert any(item[:3] == ("mark", "receipt-agent-deferred", "deferred") for item in events)

    monkeypatch.setattr(main, "_try_claim_refinement_slot", lambda receipt_id: (True, None))
    monkeypatch.setattr(main, "_refinement_executor", SimpleNamespace(submit=lambda *args: submit_calls.append(args)))
    main._schedule_operator_command_refinement("status", "auto", True, "receipt-queued")
    main._schedule_agent_run_refinement({"scenario_key": "food_spike"}, "receipt-agent-queued", message="run", mode="food_spike")
    assert len(submit_calls) == 2

    class ApiSimulation:
        async def get_state(self):
            return compact_state()

        async def get_state_lite(self):
            return {**compact_state(), "industrialDossiers": {"heavy": True}}

    identity = lambda state: state
    monkeypatch.setattr(parkpulse_api, "park_simulation", ApiSimulation())
    monkeypatch.setattr(parkpulse_api, "apply_live_weather_to_state", identity)
    monkeypatch.setattr(parkpulse_api, "apply_live_ride_ops_to_state", identity)
    monkeypatch.setattr(parkpulse_api, "apply_live_guest_flow_to_state", identity)
    monkeypatch.setattr(parkpulse_api, "apply_live_staffing_to_state", identity)
    monkeypatch.setattr(parkpulse_api, "apply_live_food_ops_to_state", identity)
    monkeypatch.setattr(parkpulse_api, "apply_live_operator_signal_to_state", identity)
    monkeypatch.setattr(parkpulse_api, "operational_doctrine_index", lambda: {"status": "ready"})
    monkeypatch.setattr(parkpulse_api, "build_audit_snapshot", lambda state: {"status": "audit"})
    monkeypatch.setattr(parkpulse_api, "build_counterfactual_forecast", lambda state: {"status": "forecast"})
    monkeypatch.setattr(parkpulse_api, "build_calibration_ledger", lambda state, forecast: {"status": "calibration", "forecast": forecast["status"]})
    monkeypatch.setattr(parkpulse_api, "build_mission_replay", lambda state: {"status": "mission"})
    monkeypatch.setattr(parkpulse_api, "build_scenario_lab", lambda state: {"status": "lab"})
    monkeypatch.setattr(parkpulse_api, "build_readiness_brief", lambda state: {"status": "brief"})
    monkeypatch.setattr(parkpulse_api, "build_learned_agent_maturity", lambda state: {"status": "maturity"})
    monkeypatch.setattr(parkpulse_api, "build_learning_evidence_ledger", lambda state: {"status": "learning"})
    async def sync_ok(state):
        return None

    monkeypatch.setattr(parkpulse_api, "sync_park_state_safe", sync_ok)

    state = run(parkpulse_api.build_park_state_response())
    lite = run(parkpulse_api.build_park_state_lite_response())
    assert state["operationsAudit"]["status"] == "audit"
    assert state["digitalTwinCalibration"]["forecast"] == "forecast"
    assert "industrialDossiers" not in lite
    assert lite["policyDoctrine"]["status"] == "ready"


def test_api_auth_analytics_and_simulation_route_wrappers(monkeypatch):
    with pytest.raises(parkpulse_api.HTTPException) as disabled:
        monkeypatch.setattr(parkpulse_api, "_dev_role_issuer_enabled", lambda: False)
        run(parkpulse_api.post_park_auth_dev_session({"role": "ops_team"}))
    assert disabled.value.status_code == 404

    monkeypatch.setattr(parkpulse_api, "_dev_role_issuer_enabled", lambda: True)
    monkeypatch.setattr(parkpulse_api, "normalize_role", lambda role: role)
    monkeypatch.setattr(parkpulse_api, "role_access_contracts", lambda role: {"role_count": 0} if role == "bad_role" else {"role_count": 1})
    with pytest.raises(parkpulse_api.HTTPException) as invalid:
        run(parkpulse_api.post_park_auth_dev_session({"role": "bad_role"}))
    assert invalid.value.status_code == 400

    monkeypatch.setattr(parkpulse_api, "_role_auth_secret", lambda: "secret")
    monkeypatch.setattr(parkpulse_api, "_role_session_ttl_seconds", lambda: 60)
    monkeypatch.setattr(parkpulse_api, "sign_role_session", lambda subject, role, secret, ttl_seconds: f"token-{subject}-{role}")
    monkeypatch.setattr(parkpulse_api, "verify_role_session", lambda token, secret: {"expires_at": "soon"})
    monkeypatch.setattr(parkpulse_api, "_signed_role_required", lambda: True)
    issued = run(parkpulse_api.post_park_auth_dev_session({"role": "ops_team", "subject": "unit"}))
    assert issued["status"] == "issued"
    assert issued["token"] == "token-unit-ops_team"

    class RouteSimulation:
        async def get_state(self):
            return compact_state()

        async def run_causal_impact_demo(self, horizon_minutes, execute):
            return {"status": "ok", "selected_action": {"id": "food"}, "horizon": horizon_minutes, "execute": execute}

        async def run_action_branch_comparison(self, horizon_minutes, execute, case_context):
            return {"status": "ok", "selected_branch": "governed", "case": case_context, "horizon": horizon_minutes, "execute": execute}

        async def reset_demo(self):
            return {"status": "reset", "message": "reset complete"}

    async def sync_ok(state):
        return None

    monkeypatch.setattr(parkpulse_api, "park_simulation", RouteSimulation())
    monkeypatch.setattr(parkpulse_api, "sync_park_state_safe", sync_ok)
    monkeypatch.setattr(parkpulse_api, "build_operational_backlog", lambda state: {"status": "backlog", "state_name": state["product"]["name"]})
    monkeypatch.setattr(parkpulse_api, "build_audit_snapshot", lambda state: {"status": "audit"})
    monkeypatch.setattr(parkpulse_api, "latest_signals", lambda limit=40: {"signals": [{"id": "signal"}]})
    monkeypatch.setattr(parkpulse_api, "latest_dispatches", lambda limit=40: [{"id": "dispatch"}])
    monkeypatch.setattr(parkpulse_api, "read_agent_ops_ledger", lambda limit=40, q=None: {"items": [{"id": "ledger"}]})
    monkeypatch.setattr(parkpulse_api, "build_incident_analytics", lambda **kwargs: {"status": "analytics", "ticket_count": 1})
    monkeypatch.setattr(parkpulse_api, "record_mongo_incident_analytics", lambda analytics: {"status": "written"})
    monkeypatch.setattr(parkpulse_api, "clear_hot_endpoint_cache", lambda: None)

    backlog = run(parkpulse_api.get_operational_backlog())
    analytics = run(parkpulse_api.get_incident_analytics())
    causal = run(parkpulse_api.run_causal_impact_demo(parkpulse_api.CausalImpactDemoRequest(horizon_minutes=12, execute=False)))
    branch = run(parkpulse_api.run_action_branch_comparison(parkpulse_api.BranchComparisonRequest(horizon_minutes=8, execute=True, case_context={"id": "case"})))
    reset = run(parkpulse_api.reset_park_demo())
    assert backlog["status"] == "backlog"
    assert analytics["mongoPersistence"]["status"] == "written"
    assert causal["state"]["product"]["name"] == "Unit Test Park"
    assert branch["selected_branch"] == "governed"
    assert reset["status"] == "reset"


def test_main_runtime_status_diagnostics_dynamic_twin_and_evidence_routes(monkeypatch):
    async def allow(*args, **kwargs):
        return True

    monkeypatch.setattr(main, "_authorize_or_send", allow)
    monkeypatch.setattr(main, "_full_runtime_status", lambda: {"loaded": True, "mode": "unit"})
    monkeypatch.setattr(main, "_api_capability_registry", lambda: {"status": "ready", "capabilities": ["unit"]})
    monkeypatch.setitem(
        sys.modules,
        "latency_diagnostics",
        SimpleNamespace(
            build_latency_diagnostics=lambda **kwargs: {"status": "ready", "mode": "latency", "full_runtime": kwargs["full_runtime"]},
            import_profile_snapshot=lambda: {"status": "profile"},
            latency_history_payload=lambda rows: {"row_count": len(rows)},
            latency_probe_snapshot=lambda: {"status": "probe"},
            schedule_latency_diagnostics_persist=lambda diagnostics, recorder: {"status": "scheduled"},
            trigger_import_profile=lambda force=False: {"started": force},
            trigger_latency_probes=lambda force=False: {"started": ["probe"] if force else []},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "scenario_eval_sweep",
        SimpleNamespace(latest_sweep_payload=lambda rows: {"status": "sweep", "rows": len(rows)}),
    )
    import mongo_memory

    monkeypatch.setattr(mongo_memory, "get_latest_memory_documents_fast", lambda collection, limit: [{"id": "eval"}])
    monkeypatch.setattr(mongo_memory, "record_latency_diagnostics_fast", lambda payload: {"status": "written"})
    monkeypatch.setattr(main, "_run_receipts", {"r1": {"id": "r1"}})

    status_runtime, runtime = run(_asgi_json("GET", "/api/park/full-runtime-status"))
    status_latency, latency = run(_asgi_json("GET", "/api/park/latency-diagnostics", query_string=b"refresh=true"))
    status_caps, caps = run(_asgi_json("GET", "/api/park/api-capabilities"))
    assert status_runtime == 200
    assert runtime["loaded"] is True
    assert status_latency == 200
    assert latency["status"] == "ready"
    assert latency["probe_trigger"]["started"] == ["probe"]
    assert status_caps == 200
    assert caps["capabilities"] == ["unit"]

    monkeypatch.setitem(
        sys.modules,
        "dynamic_operational_twin",
        SimpleNamespace(run_thunderstorm_mvp=lambda tick_minutes=5, horizon_minutes=180: {"status": "ready", "tick": tick_minutes, "horizon": horizon_minutes}),
    )
    _, twin_get = run(_asgi_json("GET", "/api/park/dynamic-twin-demo", query_string=b"tick=7&horizon=90"))
    _, twin_post = run(_asgi_json("POST", "/api/park/dynamic-twin-demo", {"tickMinutes": 3, "horizonMinutes": 30}))
    assert twin_get["tick"] == 7
    assert twin_post["horizon"] == 30

    job_id = main._evidence_refresh_job_id("route-cache")
    main._evidence_refresh_jobs[job_id] = {"id": job_id, "cache_key": "route-cache", "status": "completed", "result_payload": {"status": "ready", "mode": "unit_result"}}
    main._evidence_endpoint_cache["route-cache"] = (9999999999.0, 1.0, {"status": "cached", "mode": "unit_cache"})
    _, job_payload = run(_asgi_json("GET", f"/api/park/evidence-refresh-jobs/{job_id}"))
    _, missing_job = run(_asgi_json("GET", "/api/park/evidence-refresh-jobs/missing-job"))
    assert job_payload["status"] == "completed"
    assert job_payload["evidence_cache"]["state"] == "fresh"
    assert missing_job["status"] == "not_found"

    monkeypatch.setitem(
        sys.modules,
        "latency_diagnostics",
        SimpleNamespace(build_latency_diagnostics=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("diag offline"))),
    )
    _, latency_error = run(_asgi_json("GET", "/api/park/latency-diagnostics"))
    assert latency_error["status"] == "diagnostics_error"
