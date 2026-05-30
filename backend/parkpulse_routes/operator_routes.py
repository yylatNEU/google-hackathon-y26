from __future__ import annotations

from typing import Any


def register_operator_routes(app: Any, deps: dict[str, Any]) -> None:
    operator_command = deps["park_operator_command"]
    operator_command_request = deps["OperatorCommandRequest"]
    operator_command_refinement = deps["park_operator_command_refinement"]
    operator_command_stream = deps["park_operator_command_stream"]

    async def park_operator_command_endpoint(payload: dict[str, Any]):
        return await operator_command(operator_command_request(**payload))

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
