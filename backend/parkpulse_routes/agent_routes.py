from __future__ import annotations

from typing import Any


def register_agent_routes(app: Any, deps: dict[str, Any]) -> None:
    park_agent_run = deps["park_agent_run"]
    park_agent_run_request = deps["ParkAgentRunRequest"]

    async def park_agent_run_endpoint(payload: dict[str, Any]):
        return await park_agent_run(park_agent_run_request(**payload))

    app.add_api_route(
        "/api/park/agent-run",
        park_agent_run_endpoint,
        methods=["POST"],
    )
