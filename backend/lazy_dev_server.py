from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from env_bootstrap import load_backend_env


load_backend_env()

import main as parkpulse_lazy_main
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
    protocol_version = "HTTP/1.0"

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
        self.close_connection = True
        parsed = urlsplit(self.path)
        try:
            body = self.rfile.read(int(self.headers.get("content-length", "0") or 0))
        except TimeoutError:
            return
        if self._run_health_fast_path(parsed.path):
            return
        if self._run_experience_studio_fast_path(parsed.path, body):
            return
        if self._run_agent_handshake_fast_path(parsed.path, body):
            return
        if self._run_monitor_fast_path(parsed):
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
                        if header.lower() in {"content-length", "connection"}:
                            continue
                        header_value = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                        self.send_header(header, header_value)
                    self.send_header("connection", "close")
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
                if header.lower() == "connection":
                    continue
                header_value = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                if header.lower() == "content-length":
                    sent_content_length = True
                self.send_header(header, header_value)
            if not sent_content_length:
                self.send_header("content-length", str(len(body_bytes)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(body_bytes)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _send_direct_json(self, status: int, payload: dict[str, Any]) -> bool:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("cache-control", "no-store")
            self.send_header("access-control-allow-origin", "*")
            self.send_header("connection", "close")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return False

    def _send_direct_options(self) -> bool:
        try:
            self.send_response(204)
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET,POST,PUT,OPTIONS")
            self.send_header("access-control-allow-headers", "authorization,content-type,x-parkpulse-role,x-parkpulse-role-token")
            self.send_header("access-control-max-age", "600")
            self.send_header("connection", "close")
            self.send_header("content-length", "0")
            self.end_headers()
            return True
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return False

    def _resolve_direct_payload(self, value: Any, timeout_seconds: float = 10.0) -> Any:
        if asyncio.iscoroutine(value):
            return asyncio.run(asyncio.wait_for(value, timeout=timeout_seconds))
        return value

    def _query_value(self, query: str, key: str, default: str = "") -> str:
        values = dict(parse_qsl(query, keep_blank_values=True))
        return values.get(key, default)

    def _query_int(self, query: str, key: str, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
        try:
            value = int(self._query_value(query, key, str(default)))
        except ValueError:
            value = default
        return max(minimum, min(maximum, value))

    def _run_monitor_fast_path(self, parsed) -> bool:
        path = parsed.path
        monitor_paths = {
            "/api/park/cases",
            "/api/park/monitor-evidence",
            "/api/park/policy-doctrine",
            "/api/park/agent-monitoring",
            "/api/park/agent-monitoring/deep",
            "/api/park/agent-ops-ledger",
            "/api/park/review-training-ledger",
        }
        handles_path = path in monitor_paths or path.startswith("/api/park/policy-doctrine/")
        if not handles_path:
            return False
        if self.command == "OPTIONS":
            self._send_direct_options()
            return True
        if self.command != "GET":
            return False

        try:
            if path == "/api/park/cases":
                payload = self._resolve_direct_payload(parkpulse_lazy_main._fast_case_index())
            elif path == "/api/park/monitor-evidence":
                limit = self._query_int(parsed.query, "limit", 30, maximum=80)
                case_id = self._query_value(parsed.query, "case_id") or self._query_value(parsed.query, "caseId") or None
                payload = self._resolve_direct_payload(parkpulse_lazy_main._monitor_evidence_graph(case_id=case_id, limit=limit), timeout_seconds=15.0)
            elif path == "/api/park/policy-doctrine":
                if getattr(parkpulse_lazy_main, "_fast_operational_doctrine_index", None) is None:
                    payload = {
                        "status": "unavailable",
                        "mode": "policy_doctrine_index",
                        "policy_book_count": 0,
                        "action_case_count": 0,
                        "action_primitive_count": 0,
                        "action_cases": [],
                        "policy_refs": [],
                        "readiness_issues": ["Operational doctrine index is unavailable."],
                    }
                else:
                    payload = {"status": "ready", "mode": "policy_doctrine_index", **parkpulse_lazy_main._fast_operational_doctrine_index()}
            elif path.startswith("/api/park/policy-doctrine/"):
                payload = parkpulse_lazy_main._policy_ref_detail(unquote(path.rsplit("/", 1)[-1]))
            elif path == "/api/park/agent-monitoring":
                payload = self._resolve_direct_payload(parkpulse_lazy_main._fast_agent_monitoring())
            elif path == "/api/park/agent-monitoring/deep":
                try:
                    payload = self._resolve_direct_payload(parkpulse_lazy_main._deep_agent_monitoring(), timeout_seconds=15.0)
                except Exception as error:
                    payload = self._resolve_direct_payload(parkpulse_lazy_main._fast_agent_monitoring())
                    payload["status"] = "deep_monitoring_unavailable"
                    payload["deep_monitoring"] = {
                        "status": "unavailable",
                        "error": str(error)[:300],
                        "full_runtime": parkpulse_lazy_main._full_runtime_status(),
                    }
            elif path == "/api/park/agent-ops-ledger":
                from agent_ops_ledger import read_agent_ops_ledger

                limit = self._query_int(parsed.query, "limit", 50, maximum=80)
                search = self._query_value(parsed.query, "q").strip() or None
                payload = read_agent_ops_ledger(limit=limit, query=search)
            else:
                from live_feedback_loop import review_training_ledger

                limit = self._query_int(parsed.query, "limit", 120, maximum=500)
                payload = review_training_ledger(limit=limit)
            self._send_direct_json(200, payload if isinstance(payload, dict) else {"status": "ready", "payload": payload})
        except Exception as error:
            self._send_direct_json(200, {"status": "unavailable", "mode": "monitor_fast_path", "readiness_issues": [str(error)[:300]]})
        return True

    def _json_body(self, body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _run_health_fast_path(self, path: str) -> bool:
        if self.command != "GET" or path not in {"/", "/healthz", "/readyz"}:
            return False
        self._send_direct_json(
            200,
            {
                "service": "parkpulse-api",
                "status": "ok",
                "entrypoint": "lazy-dev-server",
                "mode": "direct_health",
                "runtime": "python-fallback",
            },
        )
        return True

    def _run_experience_studio_fast_path(self, path: str, body: bytes) -> bool:
        try:
            if path in {
                "/api/park/venue-profile",
                "/api/park/experience-studio/conversation-plan",
                "/api/park/experience-studio/draft",
                "/api/park/experience-studio/drafts",
                "/api/park/experience-studio/memory",
                "/api/park/experience-studio/readiness",
                "/api/park/experience-studio/learning-rules",
            } and self.command == "OPTIONS":
                self._send_direct_options()
                return True
            if self.command == "GET" and path == "/api/park/venue-profile":
                from venue_profile import build_venue_profile

                self._send_direct_json(200, build_venue_profile())
                return True
            if self.command == "GET" and path == "/api/park/experience-studio/drafts":
                from experience_studio import list_experience_studio_drafts

                self._send_direct_json(200, list_experience_studio_drafts())
                return True
            if self.command == "GET" and path == "/api/park/experience-studio/memory":
                from experience_studio import list_experience_studio_memory

                parsed = urlsplit(self.path)
                query = dict(parse_qsl(parsed.query, keep_blank_values=False))
                try:
                    limit = int(query.get("limit", "20"))
                except ValueError:
                    limit = 20
                self._send_direct_json(200, list_experience_studio_memory(limit=limit))
                return True
            if self.command == "GET" and path == "/api/park/experience-studio/learning-rules":
                from experience_studio import list_experience_studio_learning_rules

                parsed = urlsplit(self.path)
                query = dict(parse_qsl(parsed.query, keep_blank_values=False))
                try:
                    limit = int(query.get("limit", "30"))
                except ValueError:
                    limit = 30
                self._send_direct_json(200, list_experience_studio_learning_rules(limit=limit))
                return True
            if self.command == "GET" and path == "/api/park/experience-studio/readiness":
                from experience_studio import experience_studio_readiness

                self._send_direct_json(200, experience_studio_readiness())
                return True
            if self.command == "POST" and path.startswith("/api/park/experience-studio/drafts/") and path.endswith("/promote-rule"):
                from experience_studio import promote_experience_studio_learning_rule

                draft_id = unquote(path.removeprefix("/api/park/experience-studio/drafts/").removesuffix("/promote-rule").strip("/"))
                result = promote_experience_studio_learning_rule(draft_id, self._json_body(body))
                self._send_direct_json(200 if result.get("status") == "promoted" else 404 if result.get("status") == "not_found" else 400, result)
                return True
            if self.command == "POST" and path.startswith("/api/park/experience-studio/learning-rules/") and path.endswith("/status"):
                from experience_studio import update_experience_studio_learning_rule

                rule_id = unquote(path.removeprefix("/api/park/experience-studio/learning-rules/").removesuffix("/status").strip("/"))
                result = update_experience_studio_learning_rule(rule_id, self._json_body(body))
                self._send_direct_json(200 if result.get("status") == "updated" else 404 if result.get("status") == "not_found" else 400, result)
                return True
            if self.command == "POST" and path == "/api/park/experience-studio/conversation-plan":
                from experience_studio import build_experience_studio_conversation_plan

                self._send_direct_json(200, build_experience_studio_conversation_plan(self._json_body(body)))
                return True
            if self.command == "POST" and path == "/api/park/experience-studio/draft":
                from experience_studio import build_experience_studio_payload

                payload = self._json_body(body)
                if payload.get("useRealParkContext") is True:
                    payload["useRealParkContext"] = False
                    payload["realParkContextDeferred"] = True
                self._send_direct_json(200, asyncio.run(build_experience_studio_payload(payload, None)))
                return True
        except Exception as error:
            self._send_direct_json(500, {"status": "error", "mode": "experience_studio_fast_path", "message": str(error)[:240]})
            return True
        return False

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
            agent_handshake_scenario_catalog,
            agent_handshake_live_state_feed,
            agent_handshake_protocol_docs,
            agent_trust_registry_status,
            capability_handshake,
            certification_issuer_metadata,
            certify_agent_onboarding,
            close_session,
            commerce_agent_evaluate,
            commit_plan,
            counter_proposal,
            demo_supply_chain_handshake,
            escalate_session,
            evaluate_policy_action,
            get_agent_onboarding,
            get_session,
            identity_handshake,
            intent_handshake,
            issue_delegation_token,
            issue_agent_consent_grant,
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
            run_external_client_agent_demo,
            run_passport_second_run_demo,
            run_agent_handshake_policy_challenges,
            run_agent_handshake_scenario_evaluations,
            session_protocol_receipt,
            upsert_agent_trust_partner,
            verify_agent_certification_credential,
            verify_protocol_artifact,
        )
        payload = self._json_body(body)
        try:
            if self.command == "GET" and path == "/api/park/agent-contract":
                self._send_direct_json(200, agent_contract())
                return True
            if self.command == "GET" and path == "/api/park/agent-handshake/scenarios":
                self._send_direct_json(200, agent_handshake_scenario_catalog())
                return True
            if self.command == "GET" and path == "/api/park/agent-handshake/docs":
                self._send_direct_json(200, agent_handshake_protocol_docs())
                return True
            if self.command in {"GET", "POST"} and path == "/api/park/agent-handshake/live-state":
                self._send_direct_json(200, agent_handshake_live_state_feed(payload))
                return True
            if self.command == "POST" and path == "/api/park/agent-handshake/consent-grant":
                self._send_direct_json(200, issue_agent_consent_grant(payload))
                return True
            if self.command in {"GET", "POST"} and path == "/api/park/agent-handshake/scenario-eval":
                self._send_direct_json(200, run_agent_handshake_scenario_evaluations(payload))
                return True
            if self.command in {"GET", "POST"} and path == "/api/park/agent-handshake/policy-challenges":
                self._send_direct_json(200, run_agent_handshake_policy_challenges(payload))
                return True
            if self.command in {"GET", "POST"} and path == "/api/park/agent-handshake/external-client-demo":
                self._send_direct_json(200, run_external_client_agent_demo(payload))
                return True
            if self.command in {"GET", "POST"} and path == "/api/park/agent-handshake/passport-second-run-demo":
                self._send_direct_json(200, run_passport_second_run_demo(payload))
                return True
            if self.command == "POST" and path == "/api/park/agent-handshake/verify-artifact":
                self._send_direct_json(200, verify_protocol_artifact(payload))
                return True
            if self.command in {"GET", "POST"} and path == "/api/park/agent-handshake/supply-chain/demo":
                self._send_direct_json(200, demo_supply_chain_handshake(str(payload.get("scenario_mode") or payload.get("scenarioMode") or "supply_replenishment")))
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
                    event = str(payload.get("event") or "live")
                    self._send_direct_json(200, monitor_session(session_id, {**payload, "event": event}))
                    return True
                if self.command == "POST" and action == "escalate":
                    self._send_direct_json(200, escalate_session(session_id, payload))
                    return True
                if self.command in {"GET", "POST"} and action == "receipt":
                    self._send_direct_json(200, session_protocol_receipt(session_id, payload))
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


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    force_lazy_bridge = _env_flag("PARKPULSE_FORCE_LAZY_ASGI", True)
    use_uvicorn = _env_flag("PARKPULSE_USE_UVICORN_LAZY_SERVER", False)
    if use_uvicorn and not force_lazy_bridge:
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
