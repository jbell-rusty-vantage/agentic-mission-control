from __future__ import annotations

import pytest
from fastmcp import Client, Context

from mission_control.interfaces.mcp.coordinator_server import (
    CoordinatorPrincipal,
    create_coordinator_server,
)
from tests.support.unit.coordinator.coordinator_mcp_read_surface import FakeFacade


class StaticPrincipalResolver:
    def __init__(self, *, launch: bool = False) -> None:
        permissions = frozenset({"workflow.launch"}) if launch else frozenset()
        self.principal = CoordinatorPrincipal(
            actor_id="operator-1",
            tenant_scope="tenant-a",
            roles=frozenset({"operator"}),
            permissions=permissions,
        )

    async def resolve(self, _context: Context) -> CoordinatorPrincipal:
        return self.principal


@pytest.mark.asyncio
async def test_in_memory_mcp_bootstrap_search_resources_and_prompts() -> None:
    facade = FakeFacade()
    server = create_coordinator_server(facade, StaticPrincipalResolver())

    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools["discover_mcp_servers"].annotations.readOnlyHint is False
        assert tools["discover_agent_skills"].annotations.readOnlyHint is False
        assert tools["discover_mcp_servers"].annotations.openWorldHint is True

        bootstrap = await client.call_tool("coordinator_bootstrap")
        assert bootstrap.data["ok"] is True
        assert bootstrap.data["data"]["supported_blueprint_families"] == [
            "StageGraph",
            "GoalDirected",
        ]

        search = await client.call_tool(
            "search_capabilities",
            {
                "query": "select relevant schema context",
                "kinds": ["workflow_type"],
                "limit": 5,
            },
        )
        assert search.data["ok"] is True
        assert facade.search_requests[0]["tenant_scope"] == "tenant-a"

        resources = await client.read_resource(
            "belllabs://workflow-types/schema-context-selection/1/contract"
        )
        assert "tenant-a" in resources[0].text

        prompt = await client.get_prompt(
            "propose_workflow",
            {"objective": "research a current claim"},
        )
        assert "prompt:propose_workflow" in prompt.messages[0].content.text


@pytest.mark.asyncio
async def test_launch_is_separately_authorized_and_preparation_is_tenant_bound() -> None:
    facade = FakeFacade()
    server = create_coordinator_server(facade, StaticPrincipalResolver())

    async with Client(server) as client:
        launch = await client.call_tool(
            "launch_workflow",
            {
                "ticket_id": "ticket-1",
                "idempotency_issuer": "operator",
                "idempotency_key": "once",
            },
        )
        assert launch.data["ok"] is False
        assert launch.data["error"]["code"] == "FORBIDDEN"

        preparation = await client.call_tool(
            "prepare_workflow_launch",
            {"proposal": {"request_scope": "tenant-b"}},
        )
        assert preparation.data["ok"] is False
        assert preparation.data["error"]["code"] == "INVALID_ARGUMENT"
