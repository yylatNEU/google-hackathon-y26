from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field


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
    async def park_delivery_guest_promotion(request: DeliveryRequest):
        from park_delivery import send_guest_promotion

        dispatch = send_guest_promotion(request.payload)
        deps["clear_hot_endpoint_cache"]()
        return {"status": dispatch["status"], "dispatch": dispatch}

    @router.post("/api/park/delivery/worker-notification")
    async def park_delivery_worker_notification(request: DeliveryRequest):
        from park_delivery import send_worker_notification

        dispatch = send_worker_notification(request.payload)
        deps["clear_hot_endpoint_cache"]()
        return {"status": dispatch["status"], "dispatch": dispatch}

    @router.post("/api/park/delivery/equipment-command")
    async def park_delivery_equipment_command(request: DeliveryRequest):
        from park_delivery import send_equipment_command

        dispatch = send_equipment_command(request.payload)
        deps["clear_hot_endpoint_cache"]()
        return {"status": dispatch["status"], "dispatch": dispatch}

    @router.post("/api/park/delivery/acknowledge")
    async def park_delivery_acknowledge(request: DeliveryAckRequest):
        from park_delivery import acknowledge_dispatch, delivery_summary, latest_dispatches, response_summary

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
            "application": application,
            "state": state,
            "delivery": {
                "summary": delivery_summary(latest),
                "response": response_summary(latest),
                "dispatches": latest,
            },
        }

    @router.post("/api/park/delivery/approval-decision")
    async def park_delivery_approval_decision(request: DeliveryApprovalDecisionRequest):
        from park_delivery import delivery_summary, latest_dispatches, record_approval_decision, response_summary

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
            "approval": dispatch.get("approvalDecision"),
            "approvalDelivery": dispatch.get("approvalDelivery"),
            "delivery": {
                "summary": delivery_summary(latest),
                "response": response_summary(latest),
                "dispatches": latest,
            },
        }

    app.include_router(router)
