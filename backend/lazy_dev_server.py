from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

from env_bootstrap import load_backend_env


load_backend_env()

from main import app
from park_role_access import authorize_role_action, identity_provider_readiness, normalize_role, verify_external_role_identity, verify_role_session


_ASGI_LOOP: asyncio.AbstractEventLoop | None = None
_ASGI_LOOP_THREAD: threading.Thread | None = None


def _asgi_loop() -> asyncio.AbstractEventLoop:
    global _ASGI_LOOP, _ASGI_LOOP_THREAD
    if _ASGI_LOOP is None:
        _ASGI_LOOP = asyncio.new_event_loop()
        _ASGI_LOOP_THREAD = threading.Thread(target=_ASGI_LOOP.run_forever, name="parkpulse-asgi-loop", daemon=True)
        _ASGI_LOOP_THREAD.start()
    return _ASGI_LOOP


class LazyThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LazyAsgiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        timeout = float(os.getenv("PARKPULSE_LAZY_SOCKET_TIMEOUT", "30"))
        self.connection.settimeout(timeout)

    def do_OPTIONS(self) -> None:
        self._run_asgi()

    def do_GET(self) -> None:
        self._run_asgi()

    def do_POST(self) -> None:
        self._run_asgi()

    def do_PUT(self) -> None:
        self._run_asgi()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _run_asgi(self) -> None:
        parsed = urlsplit(self.path)
        try:
            body = self.rfile.read(int(self.headers.get("content-length", "0") or 0))
        except TimeoutError:
            return
        if self._run_agent_handshake_fast_path(parsed.path, body):
            return
        messages = [
            {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        ]
        response: dict[str, Any] = {"status": 500, "headers": [], "body": bytearray()}
        stream_started = False

        async def receive() -> dict[str, Any]:
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal stream_started
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
                response["headers"] = message.get("headers", [])
                content_type = next(
                    (
                        value.decode("latin-1") if isinstance(value, bytes) else str(value)
                        for key, value in response["headers"]
                        if (key.decode("latin-1") if isinstance(key, bytes) else str(key)).lower() == "content-type"
                    ),
                    "",
                )
                if "text/event-stream" in content_type:
                    self.send_response(int(response["status"]))
                    for key, value in response["headers"]:
                        header = key.decode("latin-1") if isinstance(key, bytes) else str(key)
                        if header.lower() == "content-length":
                            continue
                        header_value = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                        self.send_header(header, header_value)
                    self.end_headers()
                    stream_started = True
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if stream_started:
                    if body:
                        try:
                            self.wfile.write(body)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, TimeoutError):
                            return
                else:
                    response["body"].extend(body)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": self.command,
            "scheme": "http",
            "path": parsed.path,
            "raw_path": parsed.path.encode("utf-8"),
            "query_string": parsed.query.encode("utf-8"),
            "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in self.headers.items()],
            "client": self.client_address,
            "server": self.server.server_address,
        }

        try:
            future = asyncio.run_coroutine_threadsafe(app(scope, receive, send), _asgi_loop())
            future.result()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:
            if stream_started:
                error_body = f"event: run.error\ndata: {json.dumps({'message': str(error)})}\n\n".encode("utf-8")
                try:
                    self.wfile.write(error_body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                return
            response = {"status": 500, "headers": [(b"content-type", b"text/plain; charset=utf-8")], "body": bytearray(str(error).encode("utf-8"))}

        if stream_started:
            return

        body_bytes = bytes(response["body"])
        try:
            self.send_response(int(response["status"]))
            sent_content_length = False
            for key, value in response["headers"]:
                header = key.decode("latin-1") if isinstance(key, bytes) else str(key)
                header_value = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                if header.lower() == "content-length":
                    sent_content_length = True
                self.send_header(header, header_value)
            if not sent_content_length:
                self.send_header("content-length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _send_direct_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self, body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _truthy(self, value: str | None, default: bool = False) -> bool:
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _role_auth_secret(self) -> str:
        return (os.getenv("PARKPULSE_ROLE_AUTH_SECRET") or "parkpulse-local-dev-secret-change-before-production").strip()

    def _signed_role_required(self) -> bool:
        return self._truthy(os.getenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN"), True)

    def _extract_role_token(self) -> str | None:
        explicit = self.headers.get("x-parkpulse-role-token")
        if explicit:
            return explicit
        authorization = self.headers.get("authorization") or ""
        if authorization.lower().startswith("bearer "):
            return authorization.split(" ", 1)[1].strip()
        return None

    def _role_context(self, payload: dict[str, Any] | None = None, default: str = "ml_ops_admin") -> dict[str, Any]:
        headers = {str(key).lower(): str(value) for key, value in self.headers.items()}
        external_identity = verify_external_role_identity(headers, default_role=default)
        if external_identity.get("authenticated") or external_identity.get("status") == "role_unmapped":
            return external_identity
        token_status = verify_role_session(self._extract_role_token(), self._role_auth_secret())
        if token_status.get("authenticated"):
            return {
                "status": "authenticated",
                "authenticated": True,
                "auth_method": "signed_role_session",
                "role": token_status.get("role"),
                "subject": token_status.get("subject"),
                "issuer": token_status.get("issuer"),
                "expires_at": token_status.get("expires_at"),
                "token_status": token_status.get("status"),
            }
        if self._signed_role_required():
            return {
                "status": "unauthenticated",
                "authenticated": False,
                "auth_method": "signed_role_session_required",
                "role": normalize_role(None, default=default),
                "subject": "",
                "token_status": token_status.get("status"),
                "reason": token_status.get("reason") or "Signed role session token is required.",
            }
        role = self.headers.get("x-parkpulse-role") or self.headers.get("x-role")
        if not role and isinstance(payload, dict):
            role = payload.get("role") or payload.get("actor_role") or payload.get("actorRole")
        return {
            "status": "authenticated",
            "authenticated": True,
            "auth_method": "unsigned_dev_role_header",
            "role": normalize_role(str(role) if role is not None else None, default=default),
            "subject": "unsigned-local-dev",
            "token_status": token_status.get("status"),
        }

    def _authorize_trust_admin(self, resource: str, payload: dict[str, Any] | None = None) -> bool:
        identity = self._role_context(payload, default="ml_ops_admin")
        decision = authorize_role_action(identity.get("role"), "manage_agent_trust", resource=resource, default_role="ml_ops_admin")
        decision["identity"] = identity
        if not identity.get("authenticated"):
            decision["status"] = "unauthenticated"
            decision["allowed"] = False
            decision["reason"] = identity.get("reason") or "Signed role session token is required."
        if decision.get("allowed"):
            return True
        self._send_direct_json(
            401 if decision.get("status") == "unauthenticated" else 403,
            {
                "status": "forbidden",
                "mode": "role_authorization_gate",
                "authorization": decision,
                "readiness_issues": [decision.get("reason") or "Role is not authorized for this capability."],
                "boundary": "Protected ParkPulse agent-trust endpoints require a signed ml_ops_admin role session.",
            },
        )
        return False

    def _identity_readiness_payload(self) -> dict[str, Any]:
        secret = self._role_auth_secret()
        default_secret = secret == "parkpulse-local-dev-secret-change-before-production"
        provider_readiness = identity_provider_readiness()
        external_ready = bool(provider_readiness.get("external_identity_ready"))
        return {
            "status": "production_ready" if external_ready and not default_secret else "dev_signed_sessions",
            "mode": "identity_readiness",
            "signed_role_required": self._signed_role_required(),
            "dev_role_issuer_enabled": self._truthy(os.getenv("PARKPULSE_ENABLE_DEV_ROLE_ISSUER"), True),
            **provider_readiness,
            "production_ready": external_ready and not default_secret,
            "remaining_gap": None
            if external_ready and not default_secret
            else "Replace the local dev issuer with Google IAP/OIDC/Firebase and set PARKPULSE_ROLE_AUTH_SECRET before production.",
        }

    def _run_agent_handshake_fast_path(self, path: str, body: bytes) -> bool:
        if not path.startswith("/api/park/agent") and not path.startswith("/api/park/session/") and not path.startswith("/api/park/internal-agents/") and path not in {"/api/park/delegation-token", "/api/park/handshake"}:
            return False
        from agent_handshake import (
            agent_contract,
            agent_trust_registry_status,
            capability_handshake,
            certification_issuer_metadata,
            certify_agent_onboarding,
            close_session,
            commerce_agent_evaluate,
            commit_plan,
            counter_proposal,
            escalate_session,
            evaluate_policy_action,
            get_agent_onboarding,
            get_session,
            identity_handshake,
            intent_handshake,
            issue_delegation_token,
            list_agent_credential_revocations,
            list_agent_trust_audit_events,
            list_agent_trust_keys,
            list_agent_trust_partners,
            monitor_session,
            propose_plan,
            queue_agent_reroute,
            register_agent_onboarding,
            revoke_agent_certification_credential,
            rotate_agent_certification_key,
            upsert_agent_trust_partner,
            verify_agent_certification_credential,
        )
        payload = self._json_body(body)
        try:
            if self.command == "GET" and path == "/api/park/agent-contract":
                self._send_direct_json(200, agent_contract())
                return True
            if self.command == "POST" and path == "/api/park/delegation-token":
                self._send_direct_json(200, issue_delegation_token(payload))
                return True
            if self.command == "GET" and path == "/api/park/agent-onboarding/issuer":
                self._send_direct_json(200, certification_issuer_metadata())
                return True
            if self.command == "POST" and path == "/api/park/agent-onboarding/register":
                self._send_direct_json(200, register_agent_onboarding(payload))
                return True
            if self.command == "POST" and path == "/api/park/agent-onboarding/verify-credential":
                self._send_direct_json(200, verify_agent_certification_credential(payload))
                return True
            if self.command == "POST" and path == "/api/park/agent-onboarding/revoke-credential":
                if not self._authorize_trust_admin("agent_certification_revocation", payload):
                    return True
                self._send_direct_json(200, revoke_agent_certification_credential(payload))
                return True
            if self.command == "GET" and path == "/api/park/agent-trust/status":
                self._send_direct_json(200, {**agent_trust_registry_status(), "auth_boundary": self._identity_readiness_payload()})
                return True
            if self.command == "GET" and path == "/api/park/agent-trust/partners":
                if not self._authorize_trust_admin("agent_trust_partners", payload):
                    return True
                self._send_direct_json(200, list_agent_trust_partners())
                return True
            if self.command == "POST" and path == "/api/park/agent-trust/partners":
                if not self._authorize_trust_admin("agent_trust_partner_upsert", payload):
                    return True
                self._send_direct_json(200, upsert_agent_trust_partner(payload))
                return True
            if self.command == "GET" and path == "/api/park/agent-trust/keys":
                if not self._authorize_trust_admin("agent_trust_keys", payload):
                    return True
                self._send_direct_json(200, list_agent_trust_keys())
                return True
            if self.command == "POST" and path == "/api/park/agent-trust/keys/rotate":
                if not self._authorize_trust_admin("agent_trust_key_rotation", payload):
                    return True
                self._send_direct_json(200, rotate_agent_certification_key(payload))
                return True
            if self.command == "GET" and path == "/api/park/agent-trust/revocations":
                if not self._authorize_trust_admin("agent_trust_revocations", payload):
                    return True
                self._send_direct_json(200, list_agent_credential_revocations())
                return True
            if self.command == "GET" and path == "/api/park/agent-trust/audit":
                if not self._authorize_trust_admin("agent_trust_audit", payload):
                    return True
                self._send_direct_json(200, list_agent_trust_audit_events())
                return True
            if path.startswith("/api/park/agent-onboarding/"):
                parts = [unquote(part) for part in path.strip("/").split("/")]
                agent_id = parts[3] if len(parts) >= 4 else ""
                action = parts[4] if len(parts) >= 5 else ""
                if self.command == "GET" and agent_id and not action:
                    self._send_direct_json(200, get_agent_onboarding(agent_id))
                    return True
                if self.command == "POST" and agent_id and action == "certify":
                    self._send_direct_json(200, certify_agent_onboarding(agent_id, payload))
                    return True
            if self.command == "POST" and path == "/api/park/handshake":
                self._send_direct_json(200, identity_handshake(payload))
                return True
            if path.startswith("/api/park/session/"):
                parts = [unquote(part) for part in path.strip("/").split("/")]
                session_id = parts[3] if len(parts) >= 4 else ""
                action = parts[4] if len(parts) >= 5 else ""
                if self.command == "GET" and action == "monitor":
                    self._send_direct_json(200, monitor_session(session_id))
                    return True
                if self.command == "GET" and not action:
                    self._send_direct_json(200, get_session(session_id))
                    return True
                if self.command == "POST" and action == "capabilities":
                    self._send_direct_json(200, capability_handshake(session_id, payload))
                    return True
                if self.command == "POST" and action == "intent":
                    self._send_direct_json(200, intent_handshake(session_id, payload))
                    return True
                if self.command == "POST" and action == "propose":
                    self._send_direct_json(200, propose_plan(session_id, payload))
                    return True
                if self.command == "POST" and action == "counter":
                    self._send_direct_json(200, counter_proposal(session_id, payload))
                    return True
                if self.command == "POST" and action == "commit":
                    self._send_direct_json(200, commit_plan(session_id, payload))
                    return True
                if self.command == "POST" and action == "policy-check":
                    self._send_direct_json(200, evaluate_policy_action(session_id, payload))
                    return True
                if self.command == "POST" and action == "monitor":
                    self._send_direct_json(200, monitor_session(session_id, str(payload.get("event") or "live")))
                    return True
                if self.command == "POST" and action == "escalate":
                    self._send_direct_json(200, escalate_session(session_id, payload))
                    return True
                if self.command == "POST" and action == "close":
                    self._send_direct_json(200, close_session(session_id, payload))
                    return True
            if self.command == "POST" and path == "/api/park/internal-agents/commerce/evaluate":
                self._send_direct_json(200, commerce_agent_evaluate(str(payload.get("session_id") or payload.get("sessionId") or ""), payload))
                return True
            if self.command == "POST" and path == "/api/park/internal-agents/queue/reroute":
                self._send_direct_json(200, queue_agent_reroute(str(payload.get("session_id") or payload.get("sessionId") or ""), payload))
                return True
        except KeyError as error:
            self._send_direct_json(404, {"status": "not_found", "readiness_issues": [str(error)]})
            return True
        except PermissionError as error:
            self._send_direct_json(403, {"status": "delegation_rejected", "readiness_issues": [str(error)]})
            return True
        return False


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    force_lazy_bridge = os.getenv("PARKPULSE_FORCE_LAZY_ASGI", "").strip().lower() in {"1", "true", "yes", "on"}
    if not force_lazy_bridge:
        try:
            import uvicorn

            uvicorn.run(app, host=host, port=port, log_level="info")
            return
        except Exception as error:
            print(f"uvicorn startup failed, falling back to lazy ASGI bridge: {error}")
    server = LazyThreadingHTTPServer((host, port), LazyAsgiHandler)
    print(f"ParkPulse lazy dev server running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
