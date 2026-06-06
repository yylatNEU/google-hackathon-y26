import base64
import json
import sys
from types import SimpleNamespace

import gcp_trace_eval
import gcp_operations
import park_multi_agent
import park_delivery
import reliability


def clear_gcp_ops_env(monkeypatch):
    for key in (
        "ENABLE_PARKPULSE_PUBSUB",
        "PARKPULSE_PUBSUB_TOPIC",
        "ENABLE_PARKPULSE_FCM",
        "ENABLE_PARKPULSE_PSEUDO_FCM",
        "PARKPULSE_PSEUDO_FCM_OUTBOX",
        "ENABLE_PARKPULSE_WORKFLOWS",
        "PARKPULSE_WORKFLOW_ID",
        "ENABLE_PARKPULSE_FIRESTORE",
        "PARKPULSE_FIRESTORE_MIRROR",
        "PARKPULSE_FIRESTORE_COLLECTION",
        "ENABLE_VERTEX_AGENT_BUILDER",
        "VERTEX_AGENT_BUILDER_AGENT_RESOURCE",
        "VERTEX_AI_AGENT_ENGINE_RESOURCE",
        "ENABLE_PARKPULSE_DATAFLOW",
        "PARKPULSE_DATAFLOW_MIRROR",
        "PARKPULSE_DATAFLOW_TEMPLATE",
        "GOOGLE_CLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_gcp_operations_status_defaults_to_not_ready(monkeypatch):
    clear_gcp_ops_env(monkeypatch)

    status = gcp_operations.gcp_operations_status()

    assert status["pubsub"]["ready"] is False
    assert status["fcm"]["ready"] is False
    assert status["fcm"]["pseudo_enabled"] is False
    assert status["workflows"]["ready"] is False
    assert status["firestore"]["ready"] is False
    assert status["firestore"]["enabled"] is False
    assert status["agent_builder"]["ready"] is False
    assert status["agent_builder"]["agent_count"] >= 4
    assert status["dataflow"]["ready"] is False
    assert status["dataflow"]["contract"]["platform"] == "Google Cloud Dataflow"
    assert status["pubsub"]["eventarc_endpoint"] == "/api/gcp/eventarc/park-signal"


def test_decode_eventarc_pubsub_signal_extracts_payload():
    encoded = base64.b64encode(
        json.dumps(
            {
                "eventType": "parkpulse.manual.signal",
                "text": "Dragon Coaster stopped with a full queue",
                "source": "ride_ops_feed",
                "zoneId": "coasterPlaza",
                "reporterRole": "ride_lead",
            }
        ).encode("utf-8")
    ).decode("utf-8")

    decoded = gcp_operations.decode_eventarc_pubsub_signal(
        {"message": {"data": encoded, "attributes": {"source": "pubsub"}, "messageId": "m-1"}}
    )

    assert decoded["text"] == "Dragon Coaster stopped with a full queue"
    assert decoded["source"] == "ride_ops_feed"
    assert decoded["zoneId"] == "coasterPlaza"
    assert decoded["reporterRole"] == "ride_lead"
    assert decoded["event"]["messageId"] == "m-1"
    assert decoded["event"]["eventType"] == "parkpulse.manual.signal"


def test_delivery_keeps_local_outbox_when_gcp_adapters_disabled(monkeypatch, tmp_path):
    clear_gcp_ops_env(monkeypatch)
    monkeypatch.setenv("PARKPULSE_DELIVERY_OUTBOX", str(tmp_path / "outbox.jsonl"))
    park_delivery._outbox.clear()
    reliability.registry.breakers.pop("delivery_outbox.persist", None)

    dispatch = park_delivery.send_worker_notification(
        {
            "decisionId": "decision-1",
            "scenarioKey": "ride_down",
            "role": "crowd_control",
            "task": "Move to Coaster Plaza exit.",
        }
    )

    assert dispatch["durable"] is True
    assert dispatch["agentBoundary"]["status"] == "allowed"
    assert dispatch["agentBoundary"]["agent_id"] == "tool_executor_agent"
    assert dispatch["agentBoundary"]["tool"] == "dispatch_worker_task"
    assert dispatch["gcpDelivery"]["pubsub"]["status"] == "skipped"
    assert dispatch["gcpDelivery"]["fcm"]["status"] == "skipped"
    assert park_delivery.delivery_outbox_status()["durable_count"] == 1


def test_delivery_uses_tool_executor_and_blocks_missing_policy_gate(monkeypatch, tmp_path):
    clear_gcp_ops_env(monkeypatch)
    monkeypatch.setenv("PARKPULSE_DELIVERY_OUTBOX", str(tmp_path / "outbox.jsonl"))
    park_delivery._outbox.clear()
    reliability.registry.breakers.pop("delivery_outbox.persist", None)

    dispatch = park_delivery.send_equipment_command(
        {
            "agentId": "safety_policy_agent",
            "scenarioKey": "ride_down",
            "command": "Change ride controller mode.",
            "policyGateChecked": True,
        }
    )

    assert dispatch["status"] == "delivered"
    assert dispatch["durable"] is True
    assert dispatch["agentBoundary"]["status"] == "allowed"
    assert dispatch["agentBoundary"]["agent_id"] == "tool_executor_agent"
    assert dispatch["agentBoundary"]["tool"] == "dispatch_equipment_command"
    assert dispatch["agentBoundary"]["tool_contract"]["normalized"]["proposed_by"] == "safety_policy_agent"

    missing_gate = park_delivery.send_worker_notification(
        {
            "agentId": "staffing_agent",
            "scenarioKey": "ride_down",
            "task": "Move workers without a policy gate.",
        }
    )
    assert missing_gate["status"] == "blocked_by_agent_boundary"
    assert "policy_gate_checked" in missing_gate["agentBoundary"]["reason"]


def test_gcp_operations_pubsub_helpers_and_publish_paths(monkeypatch):
    clear_gcp_ops_env(monkeypatch)
    assert gcp_operations._env_bool("ENABLE_PARKPULSE_PUBSUB", default=True) is True
    monkeypatch.setenv("ENABLE_PARKPULSE_PUBSUB", "yes")
    assert gcp_operations._env_bool("ENABLE_PARKPULSE_PUBSUB") is True
    assert gcp_operations._topic_path("projects/p/topics/t") == "projects/p/topics/t"
    assert gcp_operations._topic_path("plain-topic") == "plain-topic"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    assert gcp_operations._topic_path("plain-topic") == "projects/demo-project/topics/plain-topic"
    assert gcp_operations._compact_json({"x": "y" * 20}, max_chars=12).endswith("...")
    stringified = gcp_operations._string_data({"text": "ok", "count": 3, "ready": True, "nested": {"a": 1}, "none": None})
    assert stringified == {"text": "ok", "count": "3", "ready": "true", "nested": "{\"a\":1}"}

    monkeypatch.delenv("PARKPULSE_PUBSUB_TOPIC", raising=False)
    assert gcp_operations.publish_park_event("evt", {})["reason"] == "PARKPULSE_PUBSUB_TOPIC is not set"

    monkeypatch.setenv("PARKPULSE_PUBSUB_TOPIC", "ops-topic")

    class FakeFuture:
        def result(self, timeout=0):
            return f"message-{timeout}"

    class FakePublisher:
        def __init__(self):
            self.published = []

        def publish(self, topic, message, **attrs):
            self.published.append((topic, json.loads(message.decode("utf-8")), attrs))
            return FakeFuture()

    fake_pubsub = SimpleNamespace(PublisherClient=FakePublisher)
    monkeypatch.setitem(sys.modules, "google.cloud", SimpleNamespace(pubsub_v1=fake_pubsub))
    published = gcp_operations.publish_park_event("park.test", {"a": 1}, {"extra": "yes"})
    assert published["status"] == "published"
    assert published["topic"] == "projects/demo-project/topics/ops-topic"
    assert published["dataflow"]["status"] == "mirrored"


def test_gcp_operations_credentials_and_mirror_error_edges(monkeypatch):
    clear_gcp_ops_env(monkeypatch)

    class Credentials:
        token = None

        def refresh(self, request):
            self.token = "token"

    google_auth = SimpleNamespace(default=lambda scopes: (Credentials(), None))
    google_request = SimpleNamespace(Request=lambda: object())
    monkeypatch.setitem(sys.modules, "google.auth", google_auth)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", google_request)
    assert gcp_operations._credentials(["scope"]).token == "token"

    class BadPath:
        def exists(self):
            raise OSError("path broken")

        def __str__(self):
            return "/bad/path"

    monkeypatch.setattr(gcp_operations, "_firestore_mirror_path", lambda: BadPath())
    firestore = gcp_operations.firestore_status()
    assert firestore["mirror"]["ready"] is False
    assert "path broken" in firestore["mirror"]["error"]

    monkeypatch.setattr(gcp_operations, "_dataflow_mirror_path", lambda: BadPath())
    dataflow = gcp_operations.dataflow_status()
    assert dataflow["mirror"]["ready"] is False
    assert "path broken" in dataflow["mirror"]["error"]


def test_gcp_operations_fcm_and_workflow_paths(monkeypatch):
    clear_gcp_ops_env(monkeypatch)
    dispatch = {"id": "d1", "channel": "worker_device", "status": "sent", "payload": {"task": "Check gate", "decisionId": "decision"}}
    monkeypatch.setenv("ENABLE_PARKPULSE_FCM", "true")
    assert gcp_operations.fcm_dispatch_for_delivery(dispatch)["reason"] == "GOOGLE_CLOUD_PROJECT is not set"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    assert gcp_operations.fcm_dispatch_for_delivery({**dispatch, "channel": "pager"})["reason"] == "FCM is not configured for channel pager"
    monkeypatch.setenv("PARKPULSE_FCM_WORKER_TOPIC", "")
    assert gcp_operations.fcm_dispatch_for_delivery(dispatch)["reason"] == "FCM topic is not set"

    monkeypatch.setenv("PARKPULSE_FCM_WORKER_TOPIC", "workers")
    monkeypatch.setattr(gcp_operations, "_credentials", lambda scopes: (_ for _ in ()).throw(RuntimeError("no adc")))
    assert gcp_operations.fcm_dispatch_for_delivery(dispatch)["status"] == "failed"

    monkeypatch.setattr(gcp_operations, "_credentials", lambda scopes: SimpleNamespace(token="token"))

    class FakeResponse:
        def __init__(self, status_code, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload or {}
            self.content = b"{}" if payload is not None else b""

        def json(self):
            return self._payload

    calls = []

    def fake_post(url, headers=None, json=None, timeout=0):
        calls.append((url, headers, json, timeout))
        return FakeResponse(500, "bad")

    monkeypatch.setattr(gcp_operations, "_requests_post", fake_post)
    assert gcp_operations.fcm_dispatch_for_delivery(dispatch)["http_status"] == 500
    monkeypatch.setattr(gcp_operations, "_requests_post", lambda *args, **kwargs: FakeResponse(200, payload={"name": "messages/1"}))
    assert gcp_operations.fcm_dispatch_for_delivery({**dispatch, "channel": "guest_app", "payload": {"message": "Hello"}})["status"] == "sent"

    monkeypatch.setenv("ENABLE_PARKPULSE_WORKFLOWS", "true")
    monkeypatch.delenv("PARKPULSE_WORKFLOW_ID", raising=False)
    assert gcp_operations.start_operator_workflow({"x": 1})["status"] == "skipped"
    monkeypatch.setenv("PARKPULSE_WORKFLOW_ID", "operator-approval")
    monkeypatch.setattr(gcp_operations, "_credentials", lambda scopes: (_ for _ in ()).throw(RuntimeError("workflow auth")))
    assert gcp_operations.start_operator_workflow({"x": 1})["status"] == "failed"
    monkeypatch.setattr(gcp_operations, "_credentials", lambda scopes: SimpleNamespace(token="token"))
    monkeypatch.setattr(gcp_operations, "_requests_post", lambda *args, **kwargs: FakeResponse(403, "denied"))
    assert gcp_operations.start_operator_workflow({"x": 1})["http_status"] == 403
    monkeypatch.setattr(gcp_operations, "_requests_post", lambda *args, **kwargs: FakeResponse(200, payload={"name": "exec-1"}))
    assert gcp_operations.start_operator_workflow({"x": 1})["execution"] == "exec-1"


def test_gcp_operations_enrich_and_eventarc_decode_edges(monkeypatch):
    clear_gcp_ops_env(monkeypatch)
    dispatch = {
        "id": "dispatch-1",
        "channel": "worker_device",
        "targetSystem": "radio",
        "status": "pending_operator_approval",
        "payload": {"task": "Inspect queue"},
    }
    enriched = gcp_operations.enrich_delivery_dispatch(dispatch)
    assert enriched["pubsub"]["status"] == "skipped"
    assert enriched["fcm"]["status"] == "skipped"
    assert enriched["workflow"]["status"] == "skipped"
    assert enriched["firestore"]["status"] == "mirrored"
    assert enriched["dataflow"]["status"] == "mirrored"

    invalid = gcp_operations.decode_eventarc_pubsub_signal({"message": {"data": "not-json", "attributes": {"zone_id": "z1"}}})
    assert invalid["text"] == "not-json"
    assert invalid["zoneId"] == "z1"

    raw_dict = gcp_operations.decode_eventarc_pubsub_signal(
        {"data": {"message": {"data": {"payload": {"summary": "Crowd surge", "source": "edge", "zone_id": "z2"}}}}}
    )
    assert raw_dict["text"] == "Crowd surge"
    assert raw_dict["source"] == "edge"

    fallback = gcp_operations.decode_eventarc_pubsub_signal({"description": "plain body"})
    assert fallback["text"] == "{}"


def test_firestore_operations_mirror_dispatch_and_approval(monkeypatch, tmp_path):
    clear_gcp_ops_env(monkeypatch)
    monkeypatch.setenv("PARKPULSE_FIRESTORE_MIRROR", str(tmp_path / "firestore.jsonl"))
    gcp_operations._firestore_mirror_rows.clear()

    result = gcp_operations.write_firestore_operation(
        "dispatches",
        "dispatch-1",
        {"type": "parkpulse.delivery.dispatch", "status": "pending_operator_approval"},
    )
    operations = gcp_operations.latest_firestore_operations(kind="dispatches")
    status = gcp_operations.firestore_status()

    assert result["status"] == "mirrored"
    assert result["collection"].endswith("_dispatches")
    assert result["mirror"]["durable"] is True
    assert status["mirror"]["count"] == 1
    assert operations[0]["id"] == "dispatch-1"
    assert operations[0]["payload"]["status"] == "pending_operator_approval"

    approval = gcp_operations.write_firestore_operation("approvals", "approval-1", {"decision": "approved"})
    approval_rows = gcp_operations.latest_firestore_operations(kind="approvals")
    assert approval["status"] == "mirrored"
    assert approval_rows[0]["id"] == "approval-1"
    assert approval_rows[0]["payload"]["decision"] == "approved"


def test_firestore_enabled_import_write_and_failure_paths(monkeypatch, tmp_path):
    clear_gcp_ops_env(monkeypatch)
    monkeypatch.setenv("PARKPULSE_FIRESTORE_MIRROR", str(tmp_path / "firestore.jsonl"))
    monkeypatch.setenv("ENABLE_PARKPULSE_FIRESTORE", "true")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert gcp_operations.write_firestore_operation("dispatches", "d1", {})["status"] == "skipped"

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")

    class FakeDocument:
        def __init__(self, fail=False):
            self.fail = fail

        def set(self, *args, **kwargs):
            if self.fail:
                raise RuntimeError("firestore write failed")

    class FakeCollection:
        def __init__(self, fail=False):
            self.fail = fail

        def document(self, document_id):
            return FakeDocument(fail=self.fail)

    class FakeClient:
        fail = False

        def __init__(self, project=None):
            self.project = project

        def collection(self, name):
            return FakeCollection(fail=self.fail)

    fake_firestore = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google.cloud", SimpleNamespace(firestore=fake_firestore))
    assert gcp_operations.firestore_status()["error"] is None
    written = gcp_operations.write_firestore_operation("dispatches", "d2", {"ok": True})
    assert written["status"] == "written"
    FakeClient.fail = True
    failed = gcp_operations.write_firestore_operation("dispatches", "d3", {"ok": False})
    assert failed["status"] == "failed"


def test_agent_builder_and_dataflow_contracts(monkeypatch, tmp_path):
    clear_gcp_ops_env(monkeypatch)
    monkeypatch.setenv("PARKPULSE_DATAFLOW_MIRROR", str(tmp_path / "dataflow.jsonl"))
    gcp_operations._dataflow_mirror_rows.clear()

    registry = gcp_operations.vertex_agent_builder_registry()
    agent_status = gcp_operations.vertex_agent_builder_status()
    assert registry["platform"] == "Vertex AI Agent Builder / Agent Engine"
    assert registry["contract_version"] == "parkpulse-department-agent-boundaries-v2"
    assert "policy_gate" in registry["tool_registry"]
    safety_agent = next(agent for agent in registry["agents"] if agent["id"] == "safety_policy_agent")
    bridge_agent = next(agent for agent in registry["agents"] if agent["id"] == "decision_bridge_agent")
    customer_agent = next(agent for agent in registry["agents"] if agent["id"] == "customer_support_agent")
    assert safety_agent["decision_rights"] == ["review", "block", "require_human_approval"]
    assert safety_agent["department"] == "safety"
    assert bridge_agent["department_agent"] == "Executive Agent"
    assert "validate_policy" in safety_agent["allowed_tools"]
    assert safety_agent["execution_boundary"].startswith("review only")
    assert "dispatch_equipment_command" in safety_agent["blocked_tools"]
    executor_agent = next(agent for agent in registry["agents"] if agent["id"] == "tool_executor_agent")
    assert executor_agent["decision_rights"] == ["execute_approved_action", "record_delivery_receipt", "emit_rollback_handle"]
    assert "dispatch_guest_message" in executor_agent["allowed_tools"]
    assert executor_agent["execution_boundary"].startswith("executes real receiver actions")
    assert bridge_agent["handoff_to"] == "delivery_proof_agent"
    assert customer_agent["handoff_to"] == "customer_kiosk_ui"
    assert "customer_show_route" in customer_agent["allowed_tools"]
    assert "operator_console_redirect" in customer_agent["blocked_tools"]
    assert registry["runtime_enforcement"]["pre_tool_call"].startswith("Check requested tool")
    assert park_multi_agent.enforce_agent_tool_boundary("guest_flow_agent", "dispatch_guest_message")["allowed"] is False
    blocked_guest_dispatch = park_multi_agent.enforce_agent_tool_boundary("guest_flow_agent", "dispatch_guest_message", {"policy_gate_checked": True})
    assert blocked_guest_dispatch["allowed"] is False
    assert "tool_executor_agent" in blocked_guest_dispatch["reason"]
    assert park_multi_agent.enforce_agent_tool_boundary("tool_executor_agent", "dispatch_guest_message", {"policy_gate_checked": True})["allowed"] is True
    blocked = park_multi_agent.enforce_agent_tool_boundary("safety_policy_agent", "dispatch_equipment_command")
    assert blocked["allowed"] is False
    assert blocked["status"] == "blocked"
    assert agent_status["runtime"] == "local contract"

    event = gcp_operations.write_dataflow_stream_event("parkpulse.signal", {"zone": "coaster"}, {"source": "test"})
    events = gcp_operations.latest_dataflow_events(event_type="parkpulse.signal")
    dataflow = gcp_operations.dataflow_status()
    assert event["status"] == "mirrored"
    assert events[0]["eventType"] == "parkpulse.signal"
    assert dataflow["mirror"]["count"] == 1
    assert "operator approvals" in dataflow["contract"]["sources"]

    monkeypatch.setenv("ENABLE_VERTEX_AGENT_BUILDER", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("VERTEX_AGENT_BUILDER_AGENT_RESOURCE", "projects/demo/locations/us-central1/reasoningEngines/agent")
    assert gcp_operations.vertex_agent_builder_status()["ready"] is True

    monkeypatch.setenv("ENABLE_PARKPULSE_DATAFLOW", "true")
    monkeypatch.setenv("PARKPULSE_DATAFLOW_TEMPLATE", "gs://demo/templates/parkpulse.json")
    assert gcp_operations.dataflow_status()["ready"] is True
    queued = gcp_operations.write_dataflow_stream_event("parkpulse.ready", {"ready": True})
    assert queued["status"] == "queued_for_dataflow"


def test_publish_approval_decision_writes_all_delivery_proofs(monkeypatch):
    clear_gcp_ops_env(monkeypatch)
    pubsub_calls = []
    pseudo_calls = []
    firestore_calls = []

    monkeypatch.setattr(gcp_operations, "publish_park_event", lambda event_type, payload, attributes=None: pubsub_calls.append((event_type, payload, attributes)) or {"status": "published", "dataflow": {"status": "mirrored"}})
    monkeypatch.setattr(
        gcp_operations,
        "send_pseudo_firebase_message",
        lambda topic, title, body, data, dispatch, raw: pseudo_calls.append((topic, title, body, data, dispatch, raw)) or {"status": "sent"},
    )
    monkeypatch.setattr(
        gcp_operations,
        "write_firestore_operation",
        lambda kind, document_id, payload: firestore_calls.append((kind, document_id, payload)) or {"status": "written"},
    )
    dispatch = {
        "id": "dispatch-1",
        "channel": "equipment_controller",
        "targetSystem": "ride-control",
        "status": "approved_for_execution",
        "agentBoundary": {"agent_id": "tool_executor_agent"},
        "payload": {"command": "hold dispatch"},
    }
    decision = {"decision": "approved", "actor": "lead"}
    result = gcp_operations.publish_approval_decision(dispatch, decision)

    assert result["pubsub"]["status"] == "published"
    assert result["pseudoFirebase"]["status"] == "sent"
    assert result["firestore"]["status"] == "written"
    assert result["agentBoundary"]["agent_id"] == "tool_executor_agent"
    assert pubsub_calls[0][0] == "parkpulse.delivery.approval_decision"
    assert pseudo_calls[0][1] == "ParkPulse approval decision"
    assert firestore_calls[0][0] == "approvals"


def test_pseudo_firebase_persists_topic_messages(monkeypatch, tmp_path):
    clear_gcp_ops_env(monkeypatch)
    monkeypatch.setenv("ENABLE_PARKPULSE_PSEUDO_FCM", "true")
    monkeypatch.setenv("PARKPULSE_PSEUDO_FCM_OUTBOX", str(tmp_path / "pseudo_fcm.jsonl"))
    monkeypatch.setenv("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device")
    gcp_operations._pseudo_fcm_messages.clear()

    dispatch = {
        "id": "dispatch-1",
        "channel": "worker_device",
        "targetSystem": "staff-dispatch-app",
        "status": "delivered",
        "payload": {"decisionId": "decision-1", "scenarioKey": "ride_down", "task": "Move to Coaster Plaza."},
    }

    result = gcp_operations.fcm_dispatch_for_delivery(dispatch)
    messages = gcp_operations.latest_pseudo_firebase_messages(topic="parkpulse-worker-device")
    status = gcp_operations.pseudo_firebase_status()

    assert result["status"] == "sent"
    assert result["provider"] == "pseudo_firebase"
    assert result["durable"] is True
    assert status["ready"] is True
    assert status["message_count"] == 1
    assert len(messages) == 1
    assert messages[0]["notification"]["title"] == "ParkPulse task"
    assert messages[0]["data"]["dispatchId"] == "dispatch-1"


def test_gcp_trace_eval_public_dict_configured_uninitialized_sink(monkeypatch):
    monkeypatch.setenv("ENABLE_VERTEX_CONTINUOUS_EVAL", "true")
    monkeypatch.setenv("VERTEX_EVAL_SAMPLING_RATE", "0.25")
    monkeypatch.setenv("GCP_TRACE_URL_TEMPLATE", "https://trace.example/{trace_id}")

    status = gcp_trace_eval.GcpTraceEvalStatus(
        platform="gcp",
        provider="gcp",
        project="project",
        dataset="dataset",
        trace_project="trace-project",
        trace_enabled=True,
        bigquery_ready=False,
        vertex_eval_enabled=True,
        mode="preview",
        primary_path="bigquery",
        readiness_issues=[],
        trace_export_configured=True,
        hosted_evaluator_configured=True,
        hosted_evaluator_id="eval-1",
        trace_export_ready=False,
        trace_export_error="not initialized",
    ).public_dict()

    assert status["ready"] is True
    assert status["trace"]["sink"] == "gcp_cloud_trace_configured_uninitialized"
    assert status["trace"]["export_configured"] is True
    assert status["evaluation"]["continuous_monitoring"]["status"] == "configured"
