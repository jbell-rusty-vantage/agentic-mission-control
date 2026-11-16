"""IP-009: the materializer holds each MCP server to its declared tool filter.

`exact` (the default) keeps the rule a binding always had: the server lists exactly the bound
tools. `allowlist` attaches only the bound tools of a server that lists more. Both refuse a
missing bound tool and a changed input schema. No server is started: the MCP client is a fake
that lists what each test says the server lists.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import create_model

from mission_control.adapters.deep_agents import ExactComponentRegistry, ExactDeepAgentMaterializer
from mission_control.adapters.deep_agents import materializer as materializer_module
from mission_control.adapters.deep_agents.materializer import tool_schema_digest
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef, SecretRef
from mission_control.domain.execution.contracts import (
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
)
from mission_control.domain.execution.errors import DeepAgentRuntimeDrift


def _tool(name: str, *, parameter: str = "query") -> BaseTool:
    # The parameter name is the model-facing input schema, so another name is another digest.
    schema: Any = create_model(f"{name}_input", **{parameter: (str, ...)})  # type: ignore[call-overload]
    return StructuredTool.from_function(
        func=lambda **_arguments: name,
        name=name,
        description=f"the {name} tool",
        args_schema=schema,
    )


def _server(
    name: str,
    bound: tuple[BaseTool, ...],
    *,
    tool_filter: str | None = None,
    remote: bool = False,
) -> DeepAgentMCPServerComponent:
    values: dict[str, Any] = {
        "ref": ExactDefinitionRef(
            kind=DefinitionKind.MCP_SERVER,
            logical_id=f"mcp.{name}",
            revision=1,
            digest=sha256_digest(f"mcp.{name}"),
        ),
        "server_name": name,
        "tools": tuple(
            DeepAgentMCPToolComponent(tool_name=tool.name, schema_digest=tool_schema_digest(tool))
            for tool in bound
        ),
        "schema_digest": sha256_digest(f"{name}-schema"),
        "attachment_target": "agent.main",
    }
    if remote:
        values.update(
            transport="streamable_http",
            endpoint="http://127.0.0.1:1/mcp",
            credential_refs=(SecretRef(provider="environment", key="EXAMPLE_TOKEN"),),
        )
    else:
        values.update(transport="stdio", command="server-binary", arguments=("stdio",))
    if tool_filter is not None:
        values["tool_filter"] = tool_filter
    return DeepAgentMCPServerComponent(**values)


@pytest.fixture
def listed(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[BaseTool]]:
    """What each fake server lists, keyed by server name; also records the connections."""

    servers: dict[str, list[BaseTool]] = {}

    class FakeClient:
        def __init__(self, connections: dict[str, dict[str, Any]]) -> None:
            servers["__connections__"] = connections  # type: ignore[assignment]

        async def get_tools(self, *, server_name: str | None = None) -> list[BaseTool]:
            assert server_name is not None, "tools are listed one server at a time"
            return list(servers[server_name])

    monkeypatch.setattr(materializer_module, "MultiServerMCPClient", FakeClient)
    return servers


def _materializer() -> ExactDeepAgentMaterializer:
    return ExactDeepAgentMaterializer(ExactComponentRegistry(model_factories={}))


async def test_an_allowlisted_server_attaches_exactly_the_bound_subset(
    listed: dict[str, list[BaseTool]],
) -> None:
    capture, read, ingest, sql = (
        _tool("verify_capture_source"),
        _tool("verify_read_capture"),
        _tool("ingest_apply"),
        _tool("db_sql_readonly"),
    )
    listed["capture"] = [ingest, capture, sql, read]
    server = _server("capture", (capture, read), tool_filter="allowlist", remote=True)

    tools = await _materializer()._load_mcp_tools((server,), {"environment:EXAMPLE_TOKEN": "t"})

    assert sorted(tool.name for tool in tools) == ["verify_capture_source", "verify_read_capture"]
    assert not {"ingest_apply", "db_sql_readonly"} & {tool.name for tool in tools}


async def test_an_exact_server_still_reports_drift_on_an_extra_tool(
    listed: dict[str, list[BaseTool]],
) -> None:
    search, extra = _tool("search"), _tool("write_everything")
    listed["web"] = [search, extra]

    with pytest.raises(DeepAgentRuntimeDrift, match="tool filter drift.*write_everything"):
        await _materializer()._load_mcp_tools((_server("web", (search,)),), {})

    listed["web"] = [search]
    assert [
        tool.name
        for tool in await _materializer()._load_mcp_tools((_server("web", (search,)),), {})
    ] == ["search"]


@pytest.mark.parametrize("tool_filter", ["exact", "allowlist"])
async def test_a_missing_bound_tool_is_refused_in_either_mode(
    listed: dict[str, list[BaseTool]], tool_filter: str
) -> None:
    capture, read, other = _tool("capture"), _tool("read"), _tool("other")
    listed["capture"] = [capture, other]
    server = _server("capture", (capture, read), tool_filter=tool_filter)

    with pytest.raises(DeepAgentRuntimeDrift, match="does not list bound tool.*read"):
        await _materializer()._load_mcp_tools((server,), {})


@pytest.mark.parametrize("tool_filter", ["exact", "allowlist"])
async def test_a_changed_schema_of_a_bound_tool_is_refused_in_either_mode(
    listed: dict[str, list[BaseTool]], tool_filter: str
) -> None:
    capture = _tool("capture")
    listed["capture"] = [_tool("capture", parameter="url")]
    server = _server("capture", (capture,), tool_filter=tool_filter)

    with pytest.raises(DeepAgentRuntimeDrift, match="MCP tool schema drift: capture"):
        await _materializer()._load_mcp_tools((server,), {})


async def test_an_unbound_tool_with_a_changed_schema_does_not_matter_under_an_allowlist(
    listed: dict[str, list[BaseTool]],
) -> None:
    capture = _tool("capture")
    listed["capture"] = [capture, _tool("ingest_apply", parameter="anything")]
    server = _server("capture", (capture,), tool_filter="allowlist")

    tools = await _materializer()._load_mcp_tools((server,), {})

    assert [tool.name for tool in tools] == ["capture"]


async def test_each_server_is_held_to_its_own_filter(
    listed: dict[str, list[BaseTool]],
) -> None:
    capture, search, extra = _tool("capture"), _tool("search"), _tool("ingest_apply")
    listed["capture"] = [capture, extra]
    listed["web"] = [search]
    narrowed = _server("capture", (capture,), tool_filter="allowlist", remote=True)
    exact = _server("web", (search,))

    tools = await _materializer()._load_mcp_tools(
        (narrowed, exact), {"environment:EXAMPLE_TOKEN": "token-value"}
    )

    assert [tool.name for tool in tools] == ["capture", "search"]
    connections: Any = listed["__connections__"]
    assert connections["capture"]["headers"] == {"Authorization": "Bearer token-value"}
    assert connections["web"] == {
        "transport": "stdio",
        "command": "server-binary",
        "args": ["stdio"],
        "env": None,
    }
    # The same extra tool on the exact server is drift: one server's allowlist loosens no other.
    listed["web"] = [search, extra]
    with pytest.raises(DeepAgentRuntimeDrift, match="web lists tool"):
        await _materializer()._load_mcp_tools(
            (narrowed, exact), {"environment:EXAMPLE_TOKEN": "token-value"}
        )


def test_the_filter_mode_is_part_of_the_canonical_component() -> None:
    capture = _tool("capture")
    exact = _server("capture", (capture,))
    narrowed = _server("capture", (capture,), tool_filter="allowlist")

    # `exact` is absent from the canonical form: a binding sealed before the field keeps its
    # digest. `allowlist` is present, so a sealed binding cannot be loosened after the fact.
    assert "tool_filter" not in exact.model_dump(mode="json")
    assert _server("capture", (capture,), tool_filter="exact") == exact
    assert narrowed.model_dump(mode="json")["tool_filter"] == "allowlist"
    assert sha256_digest(exact) != sha256_digest(narrowed)
    with pytest.raises(ValueError):
        _server("capture", (capture,), tool_filter="subset")
