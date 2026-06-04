from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, Request

from park_role_access import authorize_role_action, normalize_role, verify_role_session


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _role_auth_secret() -> str:
    return os.getenv("PARKPULSE_ROLE_AUTH_SECRET") or "parkpulse-local-dev-secret-change-before-production"


def _signed_role_required_for_mutation() -> bool:
    return _truthy(os.getenv("PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION"), False)


def _extract_role_token(request: Request) -> str | None:
    explicit = request.headers.get("x-parkpulse-role-token")
    if explicit:
        return explicit
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _role_identity_from_request(request: Request) -> dict[str, Any]:
    token_status = verify_role_session(_extract_role_token(request), _role_auth_secret())
    if token_status.get("authenticated"):
        return {
            "status": "authenticated",
            "authenticated": True,
            "auth_method": "signed_role_session",
            "role": token_status.get("role"),
            "subject": token_status.get("subject"),
            "token_status": token_status.get("status"),
        }
    role_header = request.headers.get("x-parkpulse-role") or request.headers.get("x-role")
    return {
        "status": "unauthenticated",
        "authenticated": False,
        "auth_method": "role_header_fallback",
        "role": normalize_role(role_header, default="ops_team"),
        "token_status": token_status.get("status"),
        "reason": token_status.get("reason"),
    }


def _enforce_role_capability(request: Request, capability: str, resource: str) -> dict[str, Any]:
    identity = _role_identity_from_request(request)
    authorization = authorize_role_action(str(identity.get("role") or "ops_team"), capability, resource=resource, default_role="ops_team")
    authorization["identity"] = identity
    if _signed_role_required_for_mutation() and not identity.get("authenticated"):
        authorization["allowed"] = False
        authorization["status"] = "blocked"
        authorization["reason"] = "Signed ParkPulse role session is required for this mutation."
    try:
        from park_role_access_audit import record_role_access_audit_event

        record_role_access_audit_event(
            "mutation_allowed" if authorization.get("allowed") is True else "mutation_denied",
            role=authorization.get("role"),
            subject=identity.get("subject"),
            capability=capability,
            resource=resource,
            status=authorization.get("status"),
            reason=authorization.get("reason"),
        )
    except Exception:
        pass
    if authorization.get("allowed") is not True:
        raise HTTPException(status_code=403, detail={"status": "blocked", "mode": "role_access_enforcement", "authorization": authorization})
    return authorization


def register_operator_routes(app: Any, deps: dict[str, Any]) -> None:
    operator_command = deps["park_operator_command"]
    operator_command_request = deps["OperatorCommandRequest"]
    operator_command_refinement = deps["park_operator_command_refinement"]
    operator_command_stream = deps["park_operator_command_stream"]

    async def park_operator_command_endpoint(http_request: Request, payload: dict[str, Any]):
        role_authorization = _enforce_role_capability(http_request, "dispatch_live_action", "operator_command")
        response = await operator_command(operator_command_request(**payload))
        if isinstance(response, dict):
            response.setdefault("role_authorization", role_authorization)
        return response

    async def park_operator_command_refinement_endpoint(refinement_id: str):
        return await operator_command_refinement(refinement_id)

    async def park_operator_command_stream_endpoint(
        message: str = "Dragon Coaster is down. Keep families happy but do not overload Food Court A.",
        mode: str = "auto",
        execute: bool = True,
    ):
        return await operator_command_stream(message=message, mode=mode, execute=execute)

    app.add_api_route(
        "/api/park/operator-command",
        park_operator_command_endpoint,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/park/operator-command/refinement/{refinement_id}",
        park_operator_command_refinement_endpoint,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/park/operator-command/stream",
        park_operator_command_stream_endpoint,
        methods=["GET"],
    )
