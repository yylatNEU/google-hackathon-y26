from dynamic_operational_twin import run_thunderstorm_mvp


def test_thunderstorm_mvp_returns_three_policy_branches():
    payload = run_thunderstorm_mvp()

    assert payload["status"] == "success"
    assert payload["scenario"]["totalGuests"] == 18_000
    assert payload["scenario"]["tickMinutes"] == 5
    assert payload["scenario"]["horizonMinutes"] == 180
    assert [policy["policyId"] for policy in payload["policies"]] == [
        "do_nothing",
        "notify",
        "full_intervention",
    ]
    assert len(payload["policies"][0]["series"]) == 37
    assert set(payload["engines"]) >= {
        "guest_flow",
        "queue",
        "capacity",
        "staff_constraint",
        "weather",
        "rule_derived_decision_intervention",
    }
    assert payload["decisionModel"]["mode"] == "simple_rules_derived"


def test_full_intervention_outperforms_no_action_on_pressure_and_satisfaction():
    payload = run_thunderstorm_mvp()
    by_policy = {policy["policyId"]: policy for policy in payload["policies"]}
    no_action = by_policy["do_nothing"]["summary"]
    full = by_policy["full_intervention"]["summary"]

    assert full["peakIndoorQueuePressure"] < no_action["peakIndoorQueuePressure"]
    assert full["peakFoodWaitMinutes"] < no_action["peakFoodWaitMinutes"]
    assert full["peakStaffStress"] < no_action["peakStaffStress"]
    assert full["finalGuestSatisfaction"] > no_action["finalGuestSatisfaction"]
    assert payload["comparison"]["lowestIndoorPressurePolicy"] == "full_intervention"


def test_dynamic_series_captures_weather_closure_and_delayed_staff_effect():
    payload = run_thunderstorm_mvp()
    full = next(policy for policy in payload["policies"] if policy["policyId"] == "full_intervention")
    series_by_minute = {point["minute"]: point for point in full["series"]}
    intervention_labels = [item["label"] for item in full["interventions"]]
    intervention_rule_ids = [item["ruleId"] for item in full["interventions"]]

    assert series_by_minute[90]["outdoorRidesClosed"] is True
    assert series_by_minute[150]["outdoorRidesClosed"] is True
    assert series_by_minute[180]["outdoorRidesClosed"] is False
    assert "Staff transfer started" in intervention_labels
    assert "Backup food stand opened" in intervention_labels
    assert "staff_stress_transfer" in intervention_rule_ids
    assert all(item["source"] == "simple_rules_derived_decision_engine" for item in full["interventions"])
    no_action = next(policy for policy in payload["policies"] if policy["policyId"] == "do_nothing")
    no_action_by_minute = {point["minute"]: point for point in no_action["series"]}
    assert series_by_minute[60]["staffStress"] < no_action_by_minute[60]["staffStress"]
