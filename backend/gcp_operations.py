from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_pseudo_fcm_messages: list[dict[str, Any]] = []
_firestore_mirror_rows: list[dict[str, Any]] = []
_dataflow_mirror_rows: list[dict[str, Any]] = []


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _project_id() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _pseudo_fcm_path() -> Path:
    configured = os.getenv("PARKPULSE_PSEUDO_FCM_OUTBOX", "").strip()
    if configured:
        return Path(configured)
    return _runtime_dir() / "pseudo_firebase_messages.jsonl"


def _firestore_mirror_path() -> Path:
    configured = os.getenv("PARKPULSE_FIRESTORE_MIRROR", "").strip()
    if configured:
        return Path(configured)
    return _runtime_dir() / "firestore_operations.jsonl"


def _firestore_collection(kind: str) -> str:
    default_root = os.getenv("PARKPULSE_FIRESTORE_COLLECTION", "parkpulse_operations").strip() or "parkpulse_operations"
    specific = os.getenv(f"PARKPULSE_FIRESTORE_{kind.upper()}_COLLECTION", "").strip()
    return specific or f"{default_root}_{kind}"


def _dataflow_mirror_path() -> Path:
    configured = os.getenv("PARKPULSE_DATAFLOW_MIRROR", "").strip()
    if configured:
        return Path(configured)
    return _runtime_dir() / "dataflow_stream_events.jsonl"


def _topic_path(raw_topic: str) -> str:
    topic = raw_topic.strip()
    if topic.startswith("projects/"):
        return topic
    project = _project_id()
    if not project:
        return topic
    return f"projects/{project}/topics/{topic}"


def _credentials(scopes: list[str]):
    from google.auth import default as google_auth_default
    from google.auth.transport.requests import Request as GoogleAuthRequest

    credentials, _ = google_auth_default(scopes=scopes)
    credentials.refresh(GoogleAuthRequest())
    return credentials


def _requests_post(*args, **kwargs):
    import requests

    return requests.post(*args, **kwargs)


def _compact_json(value: Any, max_chars: int = 700) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    if len(encoded) <= max_chars:
        return encoded
    return encoded[: max_chars - 3] + "..."


def _string_data(payload: dict[str, Any]) -> dict[str, str]:
    data: dict[str, str] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str):
            data[key] = value[:900]
        elif isinstance(value, (int, float, bool)):
            data[key] = str(value).lower() if isinstance(value, bool) else str(value)
        else:
            data[key] = _compact_json(value, max_chars=900)
    return data


def gcp_operations_status() -> dict[str, Any]:
    project = _project_id()
    pubsub_topic = os.getenv("PARKPULSE_PUBSUB_TOPIC", "").strip()
    workflow = os.getenv("PARKPULSE_WORKFLOW_ID", "").strip()
    fcm_guest_topic = os.getenv("PARKPULSE_FCM_GUEST_TOPIC", "parkpulse-guest-app").strip()
    fcm_worker_topic = os.getenv("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device").strip()
    pseudo_fcm = pseudo_firebase_status()
    firestore = firestore_status()
    return {
        "platform": "GCP operations adapters",
        "project": project or None,
        "pubsub": {
            "enabled": _env_bool("ENABLE_PARKPULSE_PUBSUB"),
            "topic": _topic_path(pubsub_topic) if pubsub_topic else None,
            "eventarc_endpoint": "/api/gcp/eventarc/park-signal",
            "ready": bool(project and pubsub_topic and _env_bool("ENABLE_PARKPULSE_PUBSUB")),
        },
        "workflows": {
            "enabled": _env_bool("ENABLE_PARKPULSE_WORKFLOWS"),
            "workflow_id": workflow or None,
            "location": os.getenv("PARKPULSE_WORKFLOW_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")),
            "ready": bool(project and workflow and _env_bool("ENABLE_PARKPULSE_WORKFLOWS")),
        },
        "fcm": {
            "enabled": _env_bool("ENABLE_PARKPULSE_FCM"),
            "pseudo_enabled": _env_bool("ENABLE_PARKPULSE_PSEUDO_FCM"),
            "mode": "firebase_cloud_messaging" if _env_bool("ENABLE_PARKPULSE_FCM") else "pseudo_firebase" if _env_bool("ENABLE_PARKPULSE_PSEUDO_FCM") else "disabled",
            "guest_topic": fcm_guest_topic,
            "worker_topic": fcm_worker_topic,
            "ready": bool((project and _env_bool("ENABLE_PARKPULSE_FCM")) or pseudo_fcm["ready"]),
            "pseudo_endpoint": "/api/gcp/pseudo-firebase/messages",
            "pseudo": pseudo_fcm,
        },
        "firestore": firestore,
        "agent_builder": vertex_agent_builder_status(),
        "dataflow": dataflow_status(),
    }


def publish_park_event(event_type: str, payload: dict[str, Any], attributes: dict[str, str] | None = None) -> dict[str, Any]:
    topic = os.getenv("PARKPULSE_PUBSUB_TOPIC", "").strip()
    envelope = {
        "eventType": event_type,
        "publishedAt": _utc_now(),
        "source": "parkpulse",
        "payload": payload,
    }
    dataflow = write_dataflow_stream_event(event_type, payload, attributes or {})
    if not _env_bool("ENABLE_PARKPULSE_PUBSUB"):
        return {"status": "skipped", "reason": "ENABLE_PARKPULSE_PUBSUB is false", "event_type": event_type, "dataflow": dataflow}
    if not topic:
        return {"status": "skipped", "reason": "PARKPULSE_PUBSUB_TOPIC is not set", "event_type": event_type, "dataflow": dataflow}
    try:
        from google.cloud import pubsub_v1
    except Exception as error:
        return {"status": "unavailable", "reason": f"google-cloud-pubsub is not importable: {error}", "event_type": event_type, "dataflow": dataflow}

    message = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    publisher = pubsub_v1.PublisherClient()
    publish_attrs = {
        "event_type": event_type,
        "source": "parkpulse",
        **(attributes or {}),
    }
    future = publisher.publish(_topic_path(topic), message, **publish_attrs)
    return {
        "status": "published",
        "event_type": event_type,
        "topic": _topic_path(topic),
        "message_id": future.result(timeout=10),
        "dataflow": dataflow,
    }


def _fcm_message_for_dispatch(dispatch: dict[str, Any]) -> tuple[str | None, str | None, str | None, dict[str, str], dict[str, Any] | None]:
    channel = str(dispatch.get("channel", ""))
    if channel == "guest_app":
        topic = os.getenv("PARKPULSE_FCM_GUEST_TOPIC", "parkpulse-guest-app").strip()
        title = "ParkPulse update"
    elif channel == "worker_device":
        topic = os.getenv("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device").strip()
        title = "ParkPulse task"
    else:
        return None, None, f"FCM is not configured for channel {channel}", {}, None
    if not topic:
        return None, None, "FCM topic is not set", {}, None

    payload = dispatch.get("payload", {}) if isinstance(dispatch.get("payload"), dict) else {}
    body = str(payload.get("message") or payload.get("task") or dispatch.get("targetSystem") or "ParkPulse action")[:240]
    data = _string_data(
        {
            "dispatchId": dispatch.get("id"),
            "channel": channel,
            "status": dispatch.get("status"),
            "decisionId": payload.get("decisionId"),
            "scenarioKey": payload.get("scenarioKey"),
            "payload": payload,
        }
    )
    return topic, title, body, data, payload


def fcm_dispatch_for_delivery(dispatch: dict[str, Any]) -> dict[str, Any]:
    topic, title, body_or_reason, data, payload = _fcm_message_for_dispatch(dispatch)
    if not topic or not title:
        return {"status": "skipped", "reason": body_or_reason or "FCM target is not configured"}
    body = body_or_reason or "ParkPulse action"

    if _env_bool("ENABLE_PARKPULSE_PSEUDO_FCM"):
        return send_pseudo_firebase_message(topic, title, body, data, dispatch, payload or {})

    if not _env_bool("ENABLE_PARKPULSE_FCM"):
        return {"status": "skipped", "reason": "ENABLE_PARKPULSE_FCM is false"}
    project = _project_id()
    if not project:
        return {"status": "skipped", "reason": "GOOGLE_CLOUD_PROJECT is not set"}

    message = {
        "message": {
            "topic": topic,
            "notification": {"title": title, "body": body},
            "data": data,
        }
    }
    try:
        credentials = _credentials([_FCM_SCOPE])
        response = _requests_post(
            f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
            headers={"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"},
            json=message,
            timeout=8,
        )
    except Exception as error:
        return {"status": "failed", "reason": str(error)[:300], "topic": topic}
    if not 200 <= response.status_code < 300:
        return {"status": "failed", "http_status": response.status_code, "reason": response.text[:300], "topic": topic}
    body_json = response.json() if response.content else {}
    return {"status": "sent", "topic": topic, "name": body_json.get("name")}


def send_pseudo_firebase_message(
    topic: str,
    title: str,
    body: str,
    data: dict[str, str],
    dispatch: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    raw = f"{topic}:{dispatch.get('id')}:{body}:{_utc_now()}".encode("utf-8")
    message_id = f"pseudo_fcm_{hashlib.sha1(raw).hexdigest()[:14]}"
    document = {
        "id": message_id,
        "createdAt": _utc_now(),
        "provider": "pseudo_firebase",
        "topic": topic,
        "notification": {"title": title, "body": body},
        "data": data,
        "dispatchId": dispatch.get("id"),
        "channel": dispatch.get("channel"),
        "targetSystem": dispatch.get("targetSystem"),
        "payload": payload,
        "status": "sent",
    }
    try:
        path = _pseudo_fcm_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(document, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        durable = True
        durability_error = None
    except Exception as error:
        durable = False
        durability_error = str(error)[:300]
    _pseudo_fcm_messages.insert(0, document)
    del _pseudo_fcm_messages[100:]
    result = {
        "status": "sent",
        "provider": "pseudo_firebase",
        "topic": topic,
        "name": message_id,
        "durable": durable,
        "endpoint": "/api/gcp/pseudo-firebase/messages",
    }
    if durability_error:
        result["durabilityError"] = durability_error
    return result


def latest_pseudo_firebase_messages(limit: int = 50, topic: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = _pseudo_fcm_path()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if topic and item.get("topic") != topic:
                        continue
                    rows.append(item)
        except Exception:
            rows = []
    if not rows:
        rows = [item for item in _pseudo_fcm_messages if not topic or item.get("topic") == topic]
    return list(reversed(rows[-limit:]))


def pseudo_firebase_status() -> dict[str, Any]:
    path = _pseudo_fcm_path()
    try:
        count = 0
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                count = sum(1 for line in file if line.strip())
        ready = _env_bool("ENABLE_PARKPULSE_PSEUDO_FCM")
        error = None
    except Exception as exc:
        count = 0
        ready = False
        error = str(exc)[:300]
    return {
        "enabled": _env_bool("ENABLE_PARKPULSE_PSEUDO_FCM"),
        "ready": ready,
        "message_count": count or len(_pseudo_fcm_messages),
        "path": str(path),
        "topics": {
            "guest": os.getenv("PARKPULSE_FCM_GUEST_TOPIC", "parkpulse-guest-app").strip(),
            "worker": os.getenv("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device").strip(),
        },
        "error": error,
    }


def firestore_status() -> dict[str, Any]:
    path = _firestore_mirror_path()
    try:
        mirror_count = 0
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                mirror_count = sum(1 for line in file if line.strip())
        mirror_ready = True
        mirror_error = None
    except Exception as exc:
        mirror_count = 0
        mirror_ready = False
        mirror_error = str(exc)[:300]
    enabled = _env_bool("ENABLE_PARKPULSE_FIRESTORE")
    importable = True
    import_error = None
    if enabled:
        try:
            from google.cloud import firestore  # noqa: F401
        except Exception as exc:
            importable = False
            import_error = str(exc)[:300]
    return {
        "enabled": enabled,
        "ready": bool(enabled and _project_id() and importable),
        "project": _project_id() or None,
        "collections": {
            "dispatches": _firestore_collection("dispatches"),
            "approvals": _firestore_collection("approvals"),
            "events": _firestore_collection("events"),
        },
        "mirror": {
            "ready": mirror_ready,
            "path": str(path),
            "count": mirror_count or len(_firestore_mirror_rows),
            "error": mirror_error,
        },
        "error": import_error,
    }


def _append_firestore_mirror(document: dict[str, Any]) -> dict[str, Any]:
    path = _firestore_mirror_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(document, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        durable = True
        durability_error = None
    except Exception as error:
        durable = False
        durability_error = str(error)[:300]
    _firestore_mirror_rows.insert(0, document)
    del _firestore_mirror_rows[200:]
    return {"durable": durable, "path": str(path), "durabilityError": durability_error}


def write_firestore_operation(kind: str, document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    collection = _firestore_collection(kind)
    document = {
        "id": document_id,
        "collection": collection,
        "kind": kind,
        "createdAt": _utc_now(),
        "payload": payload,
    }
    mirror = _append_firestore_mirror(document)
    if not _env_bool("ENABLE_PARKPULSE_FIRESTORE"):
        result = {
            "status": "mirrored",
            "provider": "local_firestore_mirror",
            "reason": "ENABLE_PARKPULSE_FIRESTORE is false",
            "collection": collection,
            "document": document_id,
            "mirror": mirror,
        }
        return result
    project = _project_id()
    if not project:
        return {"status": "skipped", "reason": "GOOGLE_CLOUD_PROJECT is not set", "collection": collection, "document": document_id, "mirror": mirror}
    try:
        from google.cloud import firestore

        client = firestore.Client(project=project)
        client.collection(collection).document(document_id).set(document, merge=True, timeout=8)
    except Exception as error:
        return {"status": "failed", "reason": str(error)[:300], "collection": collection, "document": document_id, "mirror": mirror}
    return {"status": "written", "provider": "firestore", "collection": collection, "document": document_id, "mirror": mirror}


def latest_firestore_operations(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = _firestore_mirror_path()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if kind and item.get("kind") != kind:
                        continue
                    rows.append(item)
        except Exception:
            rows = []
    if not rows:
        rows = [item for item in _firestore_mirror_rows if not kind or item.get("kind") == kind]
    return list(reversed(rows[-limit:]))


def vertex_agent_builder_registry() -> dict[str, Any]:
    from park_multi_agent import build_agent_builder_boundary_contract

    contract = build_agent_builder_boundary_contract()
    agents = [*contract["agents"]]
    return {
        "status": "registered" if _env_bool("ENABLE_VERTEX_AGENT_BUILDER") else "designed",
        "platform": "Vertex AI Agent Builder / Agent Engine",
        "contract_version": contract["contract_version"],
        "principle": contract["principle"],
        "resource": os.getenv("VERTEX_AGENT_BUILDER_AGENT_RESOURCE", os.getenv("VERTEX_AI_AGENT_ENGINE_RESOURCE", "")).strip() or None,
        "location": os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        "agents": agents,
        "tool_registry": sorted({tool for agent in agents for tool in agent["allowed_tools"]}),
        "blocked_tool_registry": sorted({tool for agent in agents for tool in agent["blocked_tools"]}),
        "handoff_rules": contract["handoff_rules"],
        "runtime_enforcement": contract["runtime_enforcement"],
        "governance": {
            "agent_identity": "IAM per agent",
            "observability": "Cloud Trace, Cloud Logging, Cloud Monitoring",
            "registry": "Approved agents and tools are explicit in this contract.",
            "runtime_protection": "Model Armor and policy gate before dispatch.",
        },
    }


def vertex_agent_builder_status() -> dict[str, Any]:
    enabled = _env_bool("ENABLE_VERTEX_AGENT_BUILDER")
    resource = os.getenv("VERTEX_AGENT_BUILDER_AGENT_RESOURCE", os.getenv("VERTEX_AI_AGENT_ENGINE_RESOURCE", "")).strip()
    registry = vertex_agent_builder_registry()
    return {
        "enabled": enabled,
        "ready": bool(enabled and _project_id() and resource),
        "project": _project_id() or None,
        "location": registry["location"],
        "resource": resource or None,
        "registry_status": registry["status"],
        "agent_count": len(registry["agents"]),
        "tool_count": len(registry["tool_registry"]),
        "runtime": "Agent Engine" if resource else "local contract",
        "contract": {
            "build": "ADK or compatible framework agents mapped to ParkPulse specialist roles.",
            "scale": "Managed Agent Engine runtime when resource is configured.",
            "govern": "IAM identity, registry-approved tools, observability, and policy gate.",
        },
    }


def _append_dataflow_mirror(document: dict[str, Any]) -> dict[str, Any]:
    path = _dataflow_mirror_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(document, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        durable = True
        durability_error = None
    except Exception as error:
        durable = False
        durability_error = str(error)[:300]
    _dataflow_mirror_rows.insert(0, document)
    del _dataflow_mirror_rows[500:]
    return {"durable": durable, "path": str(path), "durabilityError": durability_error}


def dataflow_status() -> dict[str, Any]:
    path = _dataflow_mirror_path()
    try:
        mirror_count = 0
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                mirror_count = sum(1 for line in file if line.strip())
        mirror_ready = True
        mirror_error = None
    except Exception as exc:
        mirror_count = 0
        mirror_ready = False
        mirror_error = str(exc)[:300]
    enabled = _env_bool("ENABLE_PARKPULSE_DATAFLOW")
    project = _project_id()
    return {
        "enabled": enabled,
        "ready": bool(enabled and project and os.getenv("PARKPULSE_DATAFLOW_TEMPLATE", "").strip()),
        "project": project or None,
        "location": os.getenv("PARKPULSE_DATAFLOW_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")),
        "job_name": os.getenv("PARKPULSE_DATAFLOW_JOB_NAME", "parkpulse-telemetry-stream"),
        "template": os.getenv("PARKPULSE_DATAFLOW_TEMPLATE", "").strip() or None,
        "source_topic": _topic_path(os.getenv("PARKPULSE_PUBSUB_TOPIC", "parkpulse-ops-events")),
        "sinks": {
            "bigquery": os.getenv("PARKPULSE_DATAFLOW_BIGQUERY_TABLE", "").strip() or "agent_action_outcomes",
            "firestore": _firestore_collection("events"),
        },
        "mirror": {
            "ready": mirror_ready,
            "path": str(path),
            "count": mirror_count or len(_dataflow_mirror_rows),
            "error": mirror_error,
        },
        "contract": dataflow_stream_contract(),
    }


def dataflow_stream_contract() -> dict[str, Any]:
    return {
        "name": "ParkPulse real-time telemetry stream",
        "platform": "Google Cloud Dataflow",
        "sources": [
            "Pub/Sub park events",
            "queue telemetry",
            "worker acknowledgements",
            "guest app responses",
            "equipment command results",
            "operator approvals",
        ],
        "transforms": [
            "normalize event envelope",
            "window by zone and scenario",
            "derive risk and response metrics",
            "route high-risk signals to Eventarc/Workflows",
            "write analytics-ready rows",
        ],
        "sinks": ["BigQuery", "Firestore operations state", "Cloud Monitoring custom metrics"],
        "template_type": "Flex template recommended for a new Beam pipeline",
    }


def write_dataflow_stream_event(event_type: str, payload: dict[str, Any], attributes: dict[str, str] | None = None) -> dict[str, Any]:
    raw = f"{event_type}:{_compact_json(payload, max_chars=1000)}:{_utc_now()}".encode("utf-8")
    document = {
        "id": f"dataflow_evt_{hashlib.sha1(raw).hexdigest()[:14]}",
        "createdAt": _utc_now(),
        "eventType": event_type,
        "attributes": attributes or {},
        "payload": payload,
        "pipeline": "parkpulse-telemetry-stream",
    }
    mirror = _append_dataflow_mirror(document)
    if not _env_bool("ENABLE_PARKPULSE_DATAFLOW"):
        return {
            "status": "mirrored",
            "provider": "local_dataflow_mirror",
            "reason": "ENABLE_PARKPULSE_DATAFLOW is false",
            "event_type": event_type,
            "mirror": mirror,
        }
    if not dataflow_status()["ready"]:
        return {"status": "configured_incomplete", "event_type": event_type, "mirror": mirror, "reason": "Dataflow template, project, or location is missing"}
    return {
        "status": "queued_for_dataflow",
        "provider": "dataflow",
        "event_type": event_type,
        "job_name": dataflow_status()["job_name"],
        "mirror": mirror,
    }


def latest_dataflow_events(limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = _dataflow_mirror_path()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if event_type and item.get("eventType") != event_type:
                        continue
                    rows.append(item)
        except Exception:
            rows = []
    if not rows:
        rows = [item for item in _dataflow_mirror_rows if not event_type or item.get("eventType") == event_type]
    return list(reversed(rows[-limit:]))


def start_operator_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    if not _env_bool("ENABLE_PARKPULSE_WORKFLOWS"):
        return {"status": "skipped", "reason": "ENABLE_PARKPULSE_WORKFLOWS is false"}
    project = _project_id()
    location = os.getenv("PARKPULSE_WORKFLOW_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")).strip()
    workflow_id = os.getenv("PARKPULSE_WORKFLOW_ID", "").strip()
    if not project or not location or not workflow_id:
        return {"status": "skipped", "reason": "GOOGLE_CLOUD_PROJECT, PARKPULSE_WORKFLOW_LOCATION, or PARKPULSE_WORKFLOW_ID is not set"}

    parent = f"projects/{project}/locations/{location}/workflows/{workflow_id}"
    url = f"https://workflowexecutions.googleapis.com/v1/{parent}/executions"
    try:
        credentials = _credentials([_CLOUD_PLATFORM_SCOPE])
        response = _requests_post(
            url,
            headers={"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"},
            json={"argument": json.dumps(payload, sort_keys=True, default=str)},
            timeout=10,
        )
    except Exception as error:
        return {"status": "failed", "reason": str(error)[:300], "workflow": parent}
    if not 200 <= response.status_code < 300:
        return {"status": "failed", "http_status": response.status_code, "reason": response.text[:300], "workflow": parent}
    execution = response.json() if response.content else {}
    return {"status": "started", "workflow": parent, "execution": execution.get("name")}


def enrich_delivery_dispatch(dispatch: dict[str, Any]) -> dict[str, Any]:
    payload = dispatch.get("payload", {}) if isinstance(dispatch.get("payload"), dict) else {}
    agent_boundary = dispatch.get("agentBoundary") if isinstance(dispatch.get("agentBoundary"), dict) else None
    gcp_result = {
        "pubsub": publish_park_event(
            "parkpulse.delivery.dispatch",
            {
                "dispatchId": dispatch.get("id"),
                "channel": dispatch.get("channel"),
                "targetSystem": dispatch.get("targetSystem"),
                "status": dispatch.get("status"),
                "agentBoundary": agent_boundary,
                "payload": payload,
            },
            attributes={"channel": str(dispatch.get("channel", "")), "status": str(dispatch.get("status", ""))},
        ),
        "fcm": fcm_dispatch_for_delivery(dispatch),
        "firestore": write_firestore_operation(
            "dispatches",
            str(dispatch.get("id") or f"dispatch_{hashlib.sha1(_compact_json(dispatch).encode('utf-8')).hexdigest()[:12]}"),
            {
                "type": "parkpulse.delivery.dispatch",
                "agentBoundary": agent_boundary,
                "dispatch": dispatch,
            },
        ),
    }
    gcp_result["agentBoundary"] = agent_boundary
    gcp_result["dataflow"] = gcp_result["pubsub"].get("dataflow")
    if dispatch.get("status") == "pending_operator_approval":
        callback_url = os.getenv("PARKPULSE_WORKFLOW_CALLBACK_URL", "").strip()
        gcp_result["workflow"] = start_operator_workflow(
            {
                "type": "parkpulse.delivery.approval",
                "dispatchId": dispatch.get("id"),
                "channel": dispatch.get("channel"),
                "targetSystem": dispatch.get("targetSystem"),
                "payload": payload,
                "callbackUrl": callback_url or None,
                "autoApprove": _env_bool("PARKPULSE_WORKFLOW_AUTO_APPROVE"),
            }
        )
    return gcp_result


def publish_approval_decision(dispatch: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    payload = dispatch.get("payload", {}) if isinstance(dispatch.get("payload"), dict) else {}
    agent_boundary = dispatch.get("agentBoundary") if isinstance(dispatch.get("agentBoundary"), dict) else decision.get("agentBoundary") if isinstance(decision.get("agentBoundary"), dict) else None
    event_payload = {
        "dispatchId": dispatch.get("id"),
        "channel": dispatch.get("channel"),
        "targetSystem": dispatch.get("targetSystem"),
        "status": dispatch.get("status"),
        "decision": decision,
        "agentBoundary": agent_boundary,
        "payload": payload,
    }
    pubsub = publish_park_event(
        "parkpulse.delivery.approval_decision",
        event_payload,
        attributes={
            "channel": str(dispatch.get("channel", "")),
            "status": str(dispatch.get("status", "")),
            "decision": str(decision.get("decision", "")),
        },
    )
    topic = os.getenv("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device").strip()
    pseudo_firebase = {"status": "skipped", "reason": "worker topic is not set"}
    if topic:
        title = "ParkPulse approval decision"
        body = f"{decision.get('decision', 'decision')} for {payload.get('command') or dispatch.get('targetSystem') or dispatch.get('id')}"
        pseudo_firebase = send_pseudo_firebase_message(
            topic,
            title,
            body[:240],
            _string_data(
                {
                    "dispatchId": dispatch.get("id"),
                    "channel": dispatch.get("channel"),
                    "status": dispatch.get("status"),
                    "decision": decision,
                }
            ),
            dispatch,
            {"approvalDecision": decision, "payload": payload},
        )
    firestore = write_firestore_operation(
        "approvals",
        str(dispatch.get("id") or f"approval_{hashlib.sha1(_compact_json(event_payload).encode('utf-8')).hexdigest()[:12]}"),
        {
            "type": "parkpulse.delivery.approval_decision",
            **event_payload,
        },
    )
    return {"pubsub": pubsub, "pseudoFirebase": pseudo_firebase, "firestore": firestore, "dataflow": pubsub.get("dataflow"), "agentBoundary": agent_boundary}


def decode_eventarc_pubsub_signal(body: dict[str, Any]) -> dict[str, Any]:
    message = body.get("message") if isinstance(body.get("message"), dict) else body.get("data", {}).get("message") if isinstance(body.get("data"), dict) else None
    if not isinstance(message, dict):
        message = body

    raw_data = message.get("data")
    decoded: dict[str, Any] = {}
    if isinstance(raw_data, str) and raw_data:
        try:
            decoded_text = base64.b64decode(raw_data).decode("utf-8")
            decoded = json.loads(decoded_text)
        except Exception:
            decoded = {"text": raw_data}
    elif isinstance(raw_data, dict):
        decoded = raw_data

    payload = decoded.get("payload") if isinstance(decoded.get("payload"), dict) else decoded
    attributes = message.get("attributes", {}) if isinstance(message.get("attributes"), dict) else {}
    event_type = str(decoded.get("eventType") or attributes.get("event_type") or "")
    text = (
        payload.get("text")
        or payload.get("message")
        or payload.get("description")
        or payload.get("summary")
        or _compact_json(payload, max_chars=1000)
    )
    return {
        "text": str(text),
        "source": str(payload.get("source") or attributes.get("source") or "gcp_pubsub"),
        "zoneId": payload.get("zoneId") or payload.get("zone_id") or attributes.get("zone_id"),
        "reporterRole": payload.get("reporterRole") or payload.get("reporter_role") or attributes.get("reporter_role") or "gcp_event",
        "event": {
            "eventType": event_type,
            "attributes": attributes,
            "messageId": message.get("messageId") or message.get("message_id"),
            "publishTime": message.get("publishTime") or message.get("publish_time"),
            "payload": payload,
        },
    }
