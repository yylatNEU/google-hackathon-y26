from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from park_role_access import authorize_role_action, normalize_role, verify_role_session


class DeliveryRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class DeliveryAckRequest(BaseModel):
    dispatch_id: str
    actor: str = Field(default="operator")
    choice: str = Field(default="acknowledged")
    channel: str | None = Field(default=None)


class DeliveryApprovalDecisionRequest(BaseModel):
    dispatch_id: str
    actor: str = Field(default="operator")
    decision: str = Field(default="approved")
    reason: str | None = Field(default=None)
    channel: str | None = Field(default=None)


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _role_auth_secret() -> str:
    return os.getenv("PARKPULSE_ROLE_AUTH_SECRET") or "parkpulse-local-dev-secret-change-before-production"


def _signed_role_required_for_mutation() -> bool:
    return _truthy(os.getenv("PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION"), _truthy(os.getenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN"), False))


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


def register_delivery_routes(app: Any, deps: dict[str, Any]) -> None:
    router = APIRouter()

    @router.get("/api/park/delivery/contract")
    async def park_delivery_contract():
        from park_delivery import delivery_contract

        return delivery_contract()

    @router.get("/api/park/delivery/outbox")
    async def park_delivery_outbox(limit: int = 20):
        from park_delivery import delivery_outbox_status, delivery_summary, latest_dispatches, response_summary

        dispatches = latest_dispatches(limit)
        return {
            "count": len(dispatches),
            "dispatches": dispatches,
            "summary": delivery_summary(dispatches),
            "response": response_summary(dispatches),
            "durability": delivery_outbox_status(),
        }

    @router.post("/api/park/delivery/guest-promotion")
    async def park_delivery_guest_promotion(http_request: Request, request: DeliveryRequest):
        from park_delivery import send_guest_promotion

        role_authorization = _enforce_role_capability(http_request, "dispatch_live_action", "delivery.guest_promotion")
        dispatch = send_guest_promotion(request.payload)
        deps["clear_hot_endpoint_cache"]()
        return {"status": dispatch["status"], "dispatch": dispatch, "role_authorization": role_authorization}

    @router.post("/api/park/delivery/worker-notification")
    async def park_delivery_worker_notification(http_request: Request, request: DeliveryRequest):
        from park_delivery import send_worker_notification

        role_authorization = _enforce_role_capability(http_request, "dispatch_live_action", "delivery.worker_notification")
        dispatch = send_worker_notification(request.payload)
        deps["clear_hot_endpoint_cache"]()
        return {"status": dispatch["status"], "dispatch": dispatch, "role_authorization": role_authorization}

    @router.post("/api/park/delivery/equipment-command")
    async def park_delivery_equipment_command(http_request: Request, request: DeliveryRequest):
        from park_delivery import send_equipment_command

        role_authorization = _enforce_role_capability(http_request, "dispatch_live_action", "delivery.equipment_command")
        dispatch = send_equipment_command(request.payload)
        deps["clear_hot_endpoint_cache"]()
        return {"status": dispatch["status"], "dispatch": dispatch, "role_authorization": role_authorization}

    @router.post("/api/park/delivery/acknowledge")
    async def park_delivery_acknowledge(http_request: Request, request: DeliveryAckRequest):
        from park_delivery import acknowledge_dispatch, delivery_summary, latest_dispatches, response_summary

        role_authorization = _enforce_role_capability(http_request, "acknowledge_dispatch", "delivery.acknowledge")
        dispatch = acknowledge_dispatch(
            request.dispatch_id,
            actor=request.actor,
            choice=request.choice,
            channel=request.channel,
        )
        latest = latest_dispatches(20)
        park_simulation = deps["park_simulation"]
        application = await park_simulation.apply_delivery_outcomes(latest, "receiver_acknowledgement")
        state = await park_simulation.get_state()
        await deps["sync_park_state_safe"](state)
        deps["clear_hot_endpoint_cache"]()
        return {
            "status": dispatch.get("status", "acknowledged"),
            "dispatch": dispatch,
            "role_authorization": role_authorization,
            "application": application,
            "state": state,
            "delivery": {
                "summary": delivery_summary(latest),
                "response": response_summary(latest),
                "dispatches": latest,
            },
        }

    @router.post("/api/park/delivery/approval-decision")
    async def park_delivery_approval_decision(http_request: Request, request: DeliveryApprovalDecisionRequest):
        from park_delivery import delivery_summary, latest_dispatches, record_approval_decision, response_summary

        role_authorization = _enforce_role_capability(http_request, "dispatch_live_action", "delivery.approval_decision")
        dispatch = record_approval_decision(
            request.dispatch_id,
            actor=request.actor,
            decision=request.decision,
            reason=request.reason,
            channel=request.channel,
        )
        deps["clear_hot_endpoint_cache"]()
        latest = latest_dispatches(20)
        return {
            "status": dispatch.get("status", "approval_recorded"),
            "dispatch": dispatch,
            "role_authorization": role_authorization,
            "approval": dispatch.get("approvalDecision"),
            "approvalDelivery": dispatch.get("approvalDelivery"),
            "delivery": {
                "summary": delivery_summary(latest),
                "response": response_summary(latest),
                "dispatches": latest,
            },
        }

    app.include_router(router)
