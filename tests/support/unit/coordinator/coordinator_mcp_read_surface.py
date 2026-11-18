"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_coordinator_mcp_read_surface.py.
"""

from __future__ import annotations

from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal


class FakeFacade:
    def __init__(self) -> None:
        self.search_requests: list[dict[str, object]] = []

    async def bootstrap(self, principal: CoordinatorPrincipal) -> object:
        return {
            "actor_id": principal.actor_id,
            "supported_blueprint_families": ["StageGraph", "GoalDirected"],
            "executable_blueprint_families": ["StageGraph", "GoalDirected"],
        }

    async def search(
        self,
        principal: CoordinatorPrincipal,
        request: dict[str, object],
    ) -> object:
        assert request["tenant_scope"] == principal.tenant_scope
        self.search_requests.append(request)
        return [{"exact_ref": {"kind": "workflow_type", "logical_id": "schema-context"}}]

    async def get_capability(
        self,
        _principal: CoordinatorPrincipal,
        exact_ref: dict[str, object],
    ) -> object:
        return exact_ref

    async def discover_mcp_servers(
        self,
        _principal: CoordinatorPrincipal,
        query: str,
    ) -> object:
        return [{"candidate_id": f"mcp:{query}", "authorization_state": "candidate_only"}]

    async def discover_agent_skills(
        self,
        _principal: CoordinatorPrincipal,
        query: str,
    ) -> object:
        return [{"candidate_id": f"skill:{query}", "authorization_state": "candidate_only"}]

    async def inspect_external_candidate(
        self,
        _principal: CoordinatorPrincipal,
        candidate_id: str,
    ) -> object:
        return {"candidate_id": candidate_id, "inspection_status": "pending"}

    async def validate_workflow_design(
        self,
        _principal: CoordinatorPrincipal,
        draft: dict[str, object],
    ) -> object:
        return {"valid": bool(draft)}

    async def prepare_workflow_launch(
        self,
        _principal: CoordinatorPrincipal,
        proposal: dict[str, object],
    ) -> object:
        return {"ticket_id": "ticket-1", "request_scope": proposal["request_scope"]}

    async def launch_workflow(
        self,
        _principal: CoordinatorPrincipal,
        ticket_id: str,
        idempotency_issuer: str,
        idempotency_key: str,
    ) -> object:
        return {
            "ticket_id": ticket_id,
            "run_id": f"{idempotency_issuer}:{idempotency_key}",
        }

    async def get_workflow_result(
        self,
        _principal: CoordinatorPrincipal,
        run_id: str,
    ) -> object:
        return {"run_id": run_id, "phase": "completed"}

    async def resource(
        self,
        principal: CoordinatorPrincipal,
        uri: str,
    ) -> str | dict[str, object]:
        return {"uri": uri, "tenant_scope": principal.tenant_scope}

    async def prompt(
        self,
        _principal: CoordinatorPrincipal,
        name: str,
        arguments: dict[str, str],
    ) -> str:
        return f"prompt:{name}:{arguments}"
