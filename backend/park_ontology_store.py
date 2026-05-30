from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _store_path() -> Path:
    configured = os.getenv("PARKPULSE_ONTOLOGY_STORE")
    return Path(configured) if configured else _runtime_dir() / "park_ontology_store.json"


def _events_path() -> Path:
    configured = os.getenv("PARKPULSE_ONTOLOGY_EVENTS")
    return Path(configured) if configured else _runtime_dir() / "park_ontology_events.jsonl"


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}_{hashlib.sha1(_compact_json(payload).encode('utf-8')).hexdigest()[:16]}"


def _object_key(obj: dict[str, Any]) -> str:
    return f"{obj.get('object_type') or 'Object'}:{obj.get('id') or obj.get('name') or 'unknown'}"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _append_event(event: dict[str, Any]) -> None:
    path = _events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(_compact_json(event) + "\n")


def _event_count() -> int:
    try:
        with _events_path().open("r", encoding="utf-8") as file:
            return sum(1 for _ in file)
    except OSError:
        return 0


def _public_ontology(store: dict[str, Any]) -> dict[str, Any]:
    objects_by_key = store.get("objects_by_key", {}) if isinstance(store.get("objects_by_key"), dict) else {}
    objects = list(objects_by_key.values())
    objects.sort(key=lambda item: (str(item.get("object_type") or ""), str(item.get("id") or "")))
    return {
        "ontology_id": store.get("ontology_id", "parkpulse_ops_ontology"),
        "version": store.get("version", 1),
        "generated_at": store.get("generated_at"),
        "updated_at": store.get("updated_at"),
        "storage": {
            "mode": "persistent_runtime_ontology",
            "path": str(_store_path()),
            "events_path": str(_events_path()),
            "event_count": _event_count(),
        },
        "object_types": store.get("object_types", []),
        "objects": objects,
        "relationships": store.get("relationships", []),
        "governance": store.get("governance", {}),
        "last_event": store.get("last_event"),
    }


def _new_store(seed_snapshot: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now()
    objects = {
        _object_key(obj): {
            **deepcopy(obj),
            "object_version": 1,
            "agent_state": {
                "last_action": None,
                "last_policy_gate": "unmodified",
                "last_mutation_at": None,
                "write_count": 0,
            },
        }
        for obj in seed_snapshot.get("objects", [])
        if isinstance(obj, dict)
    }
    return {
        "ontology_id": seed_snapshot.get("ontology_id", "parkpulse_ops_ontology"),
        "version": 1,
        "generated_at": now,
        "updated_at": now,
        "object_types": deepcopy(seed_snapshot.get("object_types", [])),
        "objects_by_key": objects,
        "relationships": deepcopy(seed_snapshot.get("relationships", [])),
        "governance": deepcopy(seed_snapshot.get("governance", {})),
        "last_event": None,
    }


def reconcile_ontology_with_live_state(seed_snapshot: dict[str, Any]) -> dict[str, Any]:
    path = _store_path()
    store = _read_json(path) or _new_store(seed_snapshot)
    now = _utc_now()
    objects_by_key = store.setdefault("objects_by_key", {})
    if not isinstance(objects_by_key, dict):
        objects_by_key = {}
        store["objects_by_key"] = objects_by_key

    for live_obj in seed_snapshot.get("objects", []):
        if not isinstance(live_obj, dict):
            continue
        key = _object_key(live_obj)
        existing = objects_by_key.get(key)
        if not isinstance(existing, dict):
            existing = {
                **deepcopy(live_obj),
                "object_version": 1,
                "agent_state": {
                    "last_action": None,
                    "last_policy_gate": "unmodified",
                    "last_mutation_at": None,
                    "write_count": 0,
                },
            }
            objects_by_key[key] = existing
            store["version"] = int(store.get("version") or 1) + 1
        else:
            agent_state = existing.get("agent_state") if isinstance(existing.get("agent_state"), dict) else {}
            object_version = existing.get("object_version") or 1
            existing.update(
                {
                    "object_type": live_obj.get("object_type"),
                    "id": live_obj.get("id"),
                    "name": live_obj.get("name"),
                    "status": live_obj.get("status"),
                    "freshness": live_obj.get("freshness"),
                    "permission": live_obj.get("permission"),
                    "allowed_actions": live_obj.get("allowed_actions", []),
                    "relationships": live_obj.get("relationships", []),
                    "attributes": live_obj.get("attributes", {}),
                    "object_version": object_version,
                    "agent_state": agent_state,
                }
            )

    store["object_types"] = deepcopy(seed_snapshot.get("object_types", store.get("object_types", [])))
    store["relationships"] = deepcopy(seed_snapshot.get("relationships", store.get("relationships", [])))
    store["governance"] = deepcopy(seed_snapshot.get("governance", store.get("governance", {})))
    store["updated_at"] = now
    _write_json(path, store)
    return _public_ontology(store)


def read_persistent_ontology(seed_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    store = _read_json(_store_path())
    if store is None and seed_snapshot is not None:
        return reconcile_ontology_with_live_state(seed_snapshot)
    if store is None:
        store = _new_store({"objects": []})
        _write_json(_store_path(), store)
    return _public_ontology(store)


def read_ontology_events(limit: int = 50) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    try:
        with _events_path().open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        rows = []
    bounded_limit = max(1, min(int(limit or 50), 250))
    return {
        "mode": "persistent_runtime_ontology_events",
        "count": len(rows),
        "items": list(reversed(rows[-bounded_limit:])),
        "storage": {"path": str(_events_path())},
    }


def record_ontology_turn(
    seed_snapshot: dict[str, Any],
    *,
    user_intent: str,
    affected_object_ids: list[str],
    action_policy: dict[str, Any],
    turn_contract: dict[str, Any],
    recommended_action: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    object_action_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reconcile_ontology_with_live_state(seed_snapshot)
    store = _read_json(_store_path()) or _new_store(seed_snapshot)
    now = _utc_now()
    mutation = bool(turn_contract.get("state_mutation"))
    policy_gate = action_policy.get("write") or action_policy.get("policy_gate") or "read_only"
    action_label = (recommended_action or {}).get("label") or (recommended_action or {}).get("action") or "copilot turn"
    objects_by_key = store.get("objects_by_key", {}) if isinstance(store.get("objects_by_key"), dict) else {}
    changed_keys: list[str] = []

    if mutation:
        affected_set = {str(item) for item in affected_object_ids if item}
        for key, obj in objects_by_key.items():
            if not isinstance(obj, dict):
                continue
            if str(obj.get("id")) not in affected_set and str(obj.get("name")) not in affected_set:
                continue
            agent_state = obj.get("agent_state") if isinstance(obj.get("agent_state"), dict) else {}
            agent_state.update(
                {
                    "last_action": action_label,
                    "last_policy_gate": policy_gate,
                    "last_mutation_at": now,
                    "last_map_effect": turn_contract.get("map_effect"),
                    "last_dispatch_count": turn_contract.get("dispatch_count", 0),
                    "write_count": int(agent_state.get("write_count") or 0) + 1,
                }
            )
            obj["agent_state"] = agent_state
            obj["object_version"] = int(obj.get("object_version") or 1) + 1
            changed_keys.append(key)
        if changed_keys:
            store["version"] = int(store.get("version") or 1) + 1

    event = {
        "event_id": _stable_id(
            "ont_evt",
            {
                "at": now,
                "intent": user_intent,
                "affected": affected_object_ids,
                "turn": turn_contract,
                "action": recommended_action,
            },
        ),
        "at": now,
        "event_type": "agent_object_write" if mutation else "agent_object_read",
        "user_intent": user_intent,
        "affected_object_ids": affected_object_ids,
        "changed_object_keys": changed_keys,
        "action_policy": deepcopy(action_policy),
        "turn_contract": deepcopy(turn_contract),
        "recommended_action": deepcopy(recommended_action or {}),
        "object_action_plan": deepcopy(object_action_plan or {}),
        "tool_calls": deepcopy((tool_calls or [])[:12]),
        "ontology_version": store.get("version", 1),
    }
    store["last_event"] = event
    store["updated_at"] = now
    _write_json(_store_path(), store)
    _append_event(event)
    ontology = _public_ontology(store)
    ontology["write_event"] = event
    return ontology
