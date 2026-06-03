from __future__ import annotations

import asyncio
import json

import main
from park_role_access import authorize_role_action, role_access_contracts, sign_role_session, verify_role_session


def run(coro):
    return asyncio.run(coro)


async def call_app(method: str, path: str, body: dict | None = None, query: bytes = b"", headers: dict[str, str] | None = None):
    sent = []
    received = False
    body_bytes = json.dumps(body or {}).encode("utf-8")

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    async def send(message):
        sent.append(message)

    header_rows = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
    await main.app({"type": "http", "method": method, "path": path, "query_string": query, "headers": header_rows}, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(response_body or b"{}")


def signed_headers(role: str) -> dict[str, str]:
    token = sign_role_session("unit-test", role, main._role_auth_secret(), ttl_seconds=900)
    return {"authorization": f"Bearer {token}", "x-parkpulse-role": role}


def test_role_access_contracts_separate_authority_without_seed_or_tick_bigquery():
    payload = role_access_contracts()
    roles = {role["id"]: role for role in payload["roles"]}

    assert payload["status"] == "ready"
    assert payload["uses_seed_data"] is False
    assert payload["loads_bigquery_per_tick"] is False
    assert payload["llm_control_authority"] is False
    assert set(roles) == {"customer", "onsite_worker", "ops_team", "ml_ops_admin"}
    assert "model reward or training metrics" in roles["customer"]["cannot_read"]
    assert "raw BigQuery tables" in roles["onsite_worker"]["cannot_read"]
    assert "load BigQuery per tick" in roles["ops_team"]["cannot_do"]
    assert "start offline training job" in roles["ml_ops_admin"]["can_do"]
    assert "dispatch live action" in roles["ml_ops_admin"]["cannot_do"]


def test_authorize_role_action_blocks_cross_role_authority():
    customer_ops = authorize_role_action("customer", "use_ops_chat", resource="command_center")
    ops_dispatch = authorize_role_action("ops_team", "dispatch_live_action", resource="park_action")
    admin_dispatch = authorize_role_action("ml_ops_admin", "dispatch_live_action", resource="park_action")
    ops_training = authorize_role_action("ops_team", "start_offline_training", resource="review_label_pipeline")
    admin_training = authorize_role_action("ml_ops_admin", "start_offline_training", resource="review_label_pipeline")

    assert customer_ops["allowed"] is False
    assert ops_dispatch["allowed"] is True
    assert admin_dispatch["allowed"] is False
    assert ops_training["allowed"] is False
    assert admin_training["allowed"] is True
    assert all(row["llm_control_authority"] is False for row in [customer_ops, ops_dispatch, admin_dispatch, ops_training, admin_training])


def test_role_access_contract_and_authorize_routes():
    status, payload = run(call_app("GET", "/api/park/role-access-contracts", headers=signed_headers("customer")))
    assert status == 200
    assert payload["role_count"] == 4
    assert payload["route_matrix"]["/"] == "ops_team"

    status, filtered = run(call_app("GET", "/api/park/role-access-contracts", query=b"role=ops_team", headers=signed_headers("ops_team")))
    assert status == 200
    assert filtered["role_count"] == 1
    assert filtered["roles"][0]["id"] == "ops_team"

    status, allowed = run(call_app("POST", "/api/park/role-access/authorize", {"capability": "dispatch_live_action"}, headers=signed_headers("ops_team")))
    assert status == 200
    assert allowed["status"] == "allowed"
    assert allowed["authorization"]["identity"]["auth_method"] == "signed_role_session"

    status, blocked = run(call_app("POST", "/api/park/role-access/authorize", {"role": "customer", "capability": "read_ml_training"}, headers=signed_headers("customer")))
    assert status == 200
    assert blocked["status"] == "blocked"
    assert blocked["authorization"]["role"] == "customer"
    assert blocked["authorization"]["loads_bigquery_per_tick"] is False


def test_signed_role_session_status_and_dev_issuer_boundary(monkeypatch):
    token = sign_role_session("unit-test", "ml_ops_admin", main._role_auth_secret(), ttl_seconds=900)
    verified = verify_role_session(token, main._role_auth_secret())
    assert verified["authenticated"] is True
    assert verified["role"] == "ml_ops_admin"

    status, identity = run(call_app("GET", "/api/park/auth/status", headers={"authorization": f"Bearer {token}"}))
    assert status == 200
    assert identity["identity"]["authenticated"] is True
    assert identity["identity"]["role"] == "ml_ops_admin"

    monkeypatch.delenv("PARKPULSE_ENABLE_DEV_ROLE_ISSUER", raising=False)
    status, disabled = run(call_app("POST", "/api/park/auth/dev-session", {"role": "ops_team", "subject": "unit-test"}))
    assert status == 404
    assert disabled["status"] == "disabled"

    monkeypatch.setenv("PARKPULSE_ENABLE_DEV_ROLE_ISSUER", "true")
    status, dev_session = run(call_app("POST", "/api/park/auth/dev-session", {"role": "ops_team", "subject": "unit-test"}))
    assert status == 200
    assert dev_session["status"] == "issued"
    assert verify_role_session(dev_session["token"], main._role_auth_secret())["role"] == "ops_team"
