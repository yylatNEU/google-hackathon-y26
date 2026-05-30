from scenario_eval_sweep import build_sweep_analytics_rows, summarize_scenario_result


def test_summarize_scenario_result_compares_vertex_and_internal_scores():
    result = {
        "status": "complete",
        "scenario_key": "ride_down",
        "decision_id": "decision-1",
        "outcome_id": "outcome-1",
        "optimization": {
            "selected_plan": {
                "selected_action": {
                    "label": "Reroute guests",
                    "target": "guest_flow",
                    "action": "reroute",
                    "owner": "Ops",
                }
            }
        },
        "delivery": {
            "response": {
                "status": "measured",
                "score": 88,
                "takeRate": 0.42,
                "positiveResponseRate": 0.7,
                "reactiveFollowThroughRate": 0.5,
            }
        },
        "eval": {
            "scorecard": {
                "overall": 84,
                "plan_quality_score": 91,
                "outcome_effectiveness_score": 79,
                "score_method": "70pct_receiver_outcome_30pct_plan_quality",
                "status": "passed",
                "response_score": 88,
                "policy_gate_status": "clear",
                "needs_human_approval": False,
            },
            "dimension_scores": {"Groundedness": 91, "Take rate": 42},
            "failure_reasons": [{"dimension": "Take rate"}],
            "hosted_eval": {
                "evaluator_id": "parkpulse-vertex-genai-eval",
                "vertex_result": {
                    "status": "completed",
                    "transport": "rest",
                    "location": "us-central1",
                    "result": {"score": 0.79, "explanation": "Mostly aligned."},
                },
            },
        },
    }

    summary = summarize_scenario_result(result, elapsed_ms=1234)

    assert summary["elapsed_ms"] == 1234
    assert summary["vertex"]["score_100"] == 79
    assert summary["internal"]["plan_quality_score"] == 91
    assert summary["internal"]["outcome_effectiveness_score"] == 79
    assert summary["internal"]["score_method"] == "70pct_receiver_outcome_30pct_plan_quality"
    assert summary["comparison"]["delta_vertex_minus_internal"] == -5
    assert summary["comparison"]["aligned"] is True
    assert summary["comparison"]["needs_review"] is True
    assert summary["internal"]["low_dimensions"] == [{"dimension": "Take rate", "score": 42}]


def test_build_sweep_analytics_rows_exports_eval_result_rows():
    rows = build_sweep_analytics_rows(
        {
            "sweep_id": "vertex_sweep_test",
            "scenarios": [
                {
                    "scenario_key": "ride_down",
                    "decision_id": "decision-1",
                    "status": "complete",
                    "internal": {
                        "overall": 46,
                        "outcome_effectiveness_score": 29,
                        "status": "review",
                        "score_method": "70pct_receiver_outcome_30pct_plan_quality",
                    },
                    "vertex": {
                        "score": 0.29,
                        "status": "completed",
                        "transport": "rest",
                        "evaluator_id": "parkpulse-vertex-genai-eval",
                        "explanation": "Low follow-through.",
                    },
                    "comparison": {"delta_vertex_minus_internal": -17},
                }
            ],
        }
    )

    row = rows["eval_results"][0]
    assert row["decision_id"] == "decision-1"
    assert row["scenario_key"] == "ride_down"
    assert row["source"] == "vertex_eval_scenario_sweep"
    assert row["overall"] == 46
    assert row["response_score"] == 29
    assert row["vertex_score"] == 0.29
    assert row["vertex_status"] == "completed"
