#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FULL_SCOPE = [
    "location",
    "party_size",
    "preferences",
    "accessibility_needs",
    "budget",
    "ride_preference",
    "route_plan",
    "wait_time_alert",
    "food_recommendation",
    "safety_notice",
    "compensation_offer",
    "policy_check",
    "session_commit",
]

DEFAULT_CANNOT_DO = ["auto_purchase", "share_health_data", "accept_refund_without_user"]

DEFAULT_CAN_SHARE = ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"]
DEFAULT_CAN_RECEIVE = ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"]


class ParkPulseAgentError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class ParkPulseAgentClient:
    """Dependency-free client for the ParkPulse Agent Handshake Protocol."""

    def __init__(self, api_url: str = "http://127.0.0.1:8001", timeout_seconds: int = 60):
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def post(self, path: str, body: dict[str, Any], expected_status: int = 200, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = Request(
            f"{self.api_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                status_code = response.status
        except HTTPError as error:
            payload = json.loads(error.read().decode("utf-8") or "{}")
            status_code = error.code
        except URLError as error:
            raise ParkPulseAgentError(f"Unable to reach {self.api_url}{path}: {error}") from error

        if status_code != expected_status:
            raise ParkPulseAgentError(f"{path} returned {status_code}, expected {expected_status}", status_code, payload)
        return payload

    def get(self, path: str, query: dict[str, Any] | None = None, expected_status: int = 200, headers: dict[str, str] | None = None) -> dict[str, Any]:
        suffix = f"?{urlencode(query)}" if query else ""
        request = Request(f"{self.api_url}{path}{suffix}", headers={"accept": "application/json", **(headers or {})}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                status_code = response.status
        except HTTPError as error:
            payload = json.loads(error.read().decode("utf-8") or "{}")
            status_code = error.code
        except URLError as error:
            raise ParkPulseAgentError(f"Unable to reach {self.api_url}{path}: {error}") from error

        if status_code != expected_status:
            raise ParkPulseAgentError(f"{path} returned {status_code}, expected {expected_status}", status_code, payload)
        return payload

    def register_agent(
        self,
        agent_id: str,
        display_name: str,
        requested_scopes: list[str] | None = None,
        cannot_do: list[str] | None = None,
        use_case: str = "guest_route_planning",
        partner_id: str = "demo_external_partner",
        partner_name: str = "Demo External Partner",
    ) -> dict[str, Any]:
        return self.post(
            "/api/park/agent-onboarding/register",
            {
                "agent_id": agent_id,
                "display_name": display_name,
                "partner_id": partner_id,
                "partner_name": partner_name,
                "requested_scopes": requested_scopes or FULL_SCOPE,
                "cannot_do": cannot_do or DEFAULT_CANNOT_DO,
                "use_case": use_case,
            },
        )

    def issuer_metadata(self) -> dict[str, Any]:
        return self.get("/api/park/agent-onboarding/issuer")

    def certify_agent(self, agent_id: str) -> dict[str, Any]:
        return self.post(f"/api/park/agent-onboarding/{agent_id}/certify", {})

    def verify_certification_credential(self, credential: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/park/agent-onboarding/verify-credential", {"credential": credential})

    def issue_dev_role_session(self, role: str = "ml_ops_admin", subject: str = "parkpulse-agent-client") -> dict[str, Any]:
        return self.post("/api/park/auth/dev-session", {"role": role, "subject": subject})

    def admin_headers(self) -> dict[str, str]:
        issued = self.issue_dev_role_session("ml_ops_admin")
        token = str(issued.get("token") or "")
        if not token:
            raise ParkPulseAgentError("Dev role session issuer did not return a token.", payload=issued)
        return {"x-parkpulse-role-token": token}

    def revoke_certification_credential(self, credential: dict[str, Any], reason: str = "revoked_by_external_demo") -> dict[str, Any]:
        return self.post("/api/park/agent-onboarding/revoke-credential", {"credential": credential, "reason": reason}, headers=self.admin_headers())

    def issue_delegation_token(
        self,
        subject: str,
        agent_id: str,
        scope: list[str] | None = None,
        cannot_do: list[str] | None = None,
        ttl_seconds: int = 10_800,
    ) -> dict[str, Any]:
        return self.post(
            "/api/park/delegation-token",
            {
                "subject": subject,
                "agent_id": agent_id,
                "scope": scope or FULL_SCOPE,
                "cannot_do": cannot_do or DEFAULT_CANNOT_DO,
                "ttl_seconds": ttl_seconds,
            },
        )["token"]

    def start_handshake(self, agent_id: str, represents: str, delegation_token: dict[str, Any], requested_session: str | None = None) -> dict[str, Any]:
        return self.post(
            "/api/park/handshake",
            {
                "agent_id": agent_id,
                "represents": represents,
                "proof": "signed_token",
                "requested_session": requested_session or f"external_agent_visit_{int(time.time())}",
                "delegation_token": delegation_token,
            },
        )

    def declare_capabilities(
        self,
        session_id: str,
        delegation_token: dict[str, Any],
        can_share: list[str] | None = None,
        can_receive: list[str] | None = None,
        cannot_do: list[str] | None = None,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        return self.post(
            f"/api/park/session/{session_id}/capabilities",
            {
                "can_share": can_share or DEFAULT_CAN_SHARE,
                "can_receive": can_receive or DEFAULT_CAN_RECEIVE,
                "cannot_do": cannot_do or DEFAULT_CANNOT_DO,
                "delegation_token": delegation_token,
            },
            expected_status=expected_status,
        )

    def submit_intent(self, session_id: str, delegation_token: dict[str, Any], constraints: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.post(
            f"/api/park/session/{session_id}/intent",
            {
                "goal": "maximize_family_satisfaction",
                "time_window": "3_hours",
                "constraints": constraints
                or {
                    "children": 2,
                    "avoid_wait_over_minutes": 35,
                    "avoid_thrill_rides": True,
                    "food_allergy": "peanut",
                },
                "delegation_token": delegation_token,
            },
        )

    def request_plan(self, session_id: str, delegation_token: dict[str, Any]) -> dict[str, Any]:
        return self.post(f"/api/park/session/{session_id}/propose", {"planner": "live_state", "horizon": "3_hours", "delegation_token": delegation_token})

    def request_counter_plan(self, session_id: str, delegation_token: dict[str, Any]) -> dict[str, Any]:
        return self.post(
            f"/api/park/session/{session_id}/counter",
            {
                "counter_request": "reduce walking distance",
                "priority_change": {"walking_distance": "highest", "wait_time": "medium"},
                "delegation_token": delegation_token,
            },
        )

    def commit_plan(self, session_id: str, delegation_token: dict[str, Any]) -> dict[str, Any]:
        return self.post(f"/api/park/session/{session_id}/commit", {"accepted": True, "notify_user": True, "delegation_token": delegation_token})

    def monitor_session(self, session_id: str, delegation_token: dict[str, Any]) -> dict[str, Any]:
        return self.post(f"/api/park/session/{session_id}/monitor", {"event": "live", "delegation_token": delegation_token})

    def probe_payment_gate(self, session_id: str, delegation_token: dict[str, Any], amount: int = 42) -> dict[str, Any]:
        return self.post(
            "/api/park/internal-agents/commerce/evaluate",
            {
                "session_id": session_id,
                "action": "payment",
                "amount": amount,
                "reason": "External agent proves payment is gated.",
                "delegation_token": delegation_token,
            },
        )

    def request_queue_reroute(self, session_id: str, delegation_token: dict[str, Any]) -> dict[str, Any]:
        return self.post(
            "/api/park/internal-agents/queue/reroute",
            {
                "session_id": session_id,
                "walking_priority": "highest",
                "reason": "External agent asks Queue Agent for a lower-walking route.",
                "delegation_token": delegation_token,
            },
        )
