from controlled_training_eval import _score_role
from controlled_training_generation import _bounded_examples


def _example(agent_id: str, index: int, source: str = "approved_review_label_decision") -> dict:
    return {
        "id": f"{agent_id}-{index}",
        "agent_id": agent_id,
        "split": "train",
        "training_scope": f"{agent_id}_scope",
        "source": source,
        "input": {"scenario_key": "food_spike", "policy": "bounded"},
        "expected_output": {"label": "approved", "decision": "accept"},
        "eligible_for_supervised_training": True,
        "eligible_for_reward": False,
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
    }


def test_bounded_examples_reserves_available_role_coverage():
    rows = [_example("scan_agent", index) for index in range(10)]
    rows.extend([_example("react_agent", 0), _example("proactive_agent", 0), _example("ops_chat", 0)])

    bounded = _bounded_examples(rows, 3)

    assert {row["agent_id"] for row in bounded} == {"scan_agent", "react_agent", "proactive_agent"}


def test_react_and_proactive_pass_with_approved_supervised_label_coverage():
    for agent_id in ("react_agent", "proactive_agent"):
        result = _score_role(agent_id, [_example(agent_id, 0)])

        assert result["passed"] is True
        assert result["score"] >= result["min_score"]
        assert result["failure_reasons"] == []
