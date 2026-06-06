from __future__ import annotations

import json

import park_ontology_store as ontology


def _seed():
    return {
        "ontology_id": "unit_ontology",
        "object_types": ["Ride", "Zone"],
        "objects": [
            {
                "object_type": "Ride",
                "id": "dragon",
                "name": "Dragon Coaster",
                "status": "down",
                "freshness": "live",
                "permission": "read_write",
                "allowed_actions": ["reroute"],
                "relationships": [{"type": "located_in", "target": "coasterPlaza"}],
                "attributes": {"waitMins": 55},
            },
            "bad-object",
        ],
        "relationships": [{"source": "dragon", "target": "coasterPlaza"}],
        "governance": {"write_requires_policy_gate": True},
    }


def test_ontology_store_reconciles_reads_and_handles_corrupt_files(tmp_path, monkeypatch):
    store_path = tmp_path / "ontology.json"
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("PARKPULSE_ONTOLOGY_STORE", str(store_path))
    monkeypatch.setenv("PARKPULSE_ONTOLOGY_EVENTS", str(events_path))

    assert ontology._read_json(tmp_path / "missing.json") is None
    store_path.write_text("{bad json", encoding="utf-8")
    assert ontology._read_json(store_path) is None

    public = ontology.reconcile_ontology_with_live_state(_seed())
    assert public["ontology_id"] == "unit_ontology"
    assert public["version"] == 1
    assert public["objects"][0]["id"] == "dragon"
    assert public["storage"]["event_count"] == 0

    updated_seed = _seed()
    updated_seed["objects"][0]["status"] = "normal"
    updated = ontology.reconcile_ontology_with_live_state(updated_seed)
    assert updated["objects"][0]["status"] == "normal"
    assert updated["objects"][0]["agent_state"]["write_count"] == 0

    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["objects_by_key"] = "bad"
    store_path.write_text(json.dumps(store), encoding="utf-8")
    recovered = ontology.reconcile_ontology_with_live_state(updated_seed)
    assert recovered["objects"][0]["id"] == "dragon"

    events_path.write_text('{"event_id":"a"}\nnot-json\n\n{"event_id":"b"}\n', encoding="utf-8")
    events = ontology.read_ontology_events(limit=1)
    assert events["count"] == 2
    assert events["items"][0]["event_id"] == "b"

    store_path.unlink()
    seeded = ontology.read_persistent_ontology(_seed())
    assert seeded["objects"]
    store_path.unlink()
    empty = ontology.read_persistent_ontology()
    assert empty["objects"] == []


def test_ontology_turn_records_read_and_mutation_events(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_ONTOLOGY_STORE", str(tmp_path / "ontology.json"))
    monkeypatch.setenv("PARKPULSE_ONTOLOGY_EVENTS", str(tmp_path / "events.jsonl"))
    seed = _seed()

    read_turn = ontology.record_ontology_turn(
        seed,
        user_intent="What changed?",
        affected_object_ids=["dragon"],
        action_policy={"write": "read_only"},
        turn_contract={"state_mutation": False, "map_effect": "none", "dispatch_count": 0},
        recommended_action={"label": "Inspect"},
        tool_calls=[{"tool": str(i)} for i in range(20)],
    )
    assert read_turn["write_event"]["event_type"] == "agent_object_read"
    assert read_turn["write_event"]["changed_object_keys"] == []
    assert len(read_turn["write_event"]["tool_calls"]) == 12

    write_turn = ontology.record_ontology_turn(
        seed,
        user_intent="Reroute Dragon Coaster",
        affected_object_ids=["dragon", "Dragon Coaster"],
        action_policy={"policy_gate": "approved"},
        turn_contract={"state_mutation": True, "map_effect": "queue rerouted", "dispatch_count": 2},
        recommended_action={"label": "Reroute guests"},
        object_action_plan={"target": "ride", "action": "reroute"},
    )
    dragon = next(obj for obj in write_turn["objects"] if obj["id"] == "dragon")
    assert write_turn["write_event"]["event_type"] == "agent_object_write"
    assert write_turn["write_event"]["changed_object_keys"] == ["Ride:dragon"]
    assert dragon["agent_state"]["last_action"] == "Reroute guests"
    assert dragon["agent_state"]["last_policy_gate"] == "approved"
    assert dragon["agent_state"]["write_count"] == 1
    assert ontology.read_ontology_events(limit=10)["count"] == 2
