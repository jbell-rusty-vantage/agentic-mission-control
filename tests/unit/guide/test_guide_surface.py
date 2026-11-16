"""The guide cannot drift from the surface it describes.

Every operation a guide page names is checked against the transport it is named for: the MCP
tool is on the operator server (with the arguments the call uses), the `missionctl` command is
in the argparse tree (with its flags) and the route is mounted. The tool documentation moved out
of `tools/list` is held to the same server: every documented tool exists, every tool that takes
an object the listing does not type is documented, and the four shortened descriptions point at
their full shape. No server process: the operator FastMCP server is built in memory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastmcp import Client

from mission_control.application.guide.operations import (
    OPERATIONS,
    SURFACES,
    UnknownOperation,
    operations_in,
    render_operation,
)
from mission_control.application.guide.pages import INDEX, TOPIC_IDS, load_page
from mission_control.application.guide.tool_docs import TOOL_DOCS
from mission_control.interfaces.cli.main import build_parser
from mission_control.interfaces.http.catalog import router as catalog_router
from mission_control.interfaces.http.chains import router as chains_router
from mission_control.interfaces.http.cognition_points import router as cognition_points_router
from mission_control.interfaces.http.coordinator_inbox import router as coordinator_inbox_router
from mission_control.interfaces.http.guide import router as guide_router
from mission_control.interfaces.http.human_tasks import router as human_tasks_router
from mission_control.interfaces.http.lanes import router as lanes_router
from mission_control.interfaces.http.mission_control import router as mission_router
from mission_control.interfaces.http.missions import router as missions_router
from mission_control.interfaces.http.models import router as models_router
from mission_control.interfaces.http.output_inspection import router as output_inspection_router
from mission_control.interfaces.http.selection import router as selection_router
from mission_control.interfaces.http.transcript import router as transcript_router
from mission_control.interfaces.mcp.guide_tools import (
    DESCRIBE_TOOL,
    GUIDE_RESOURCE_PREFIX,
    GUIDE_TOOL,
    INTERVIEW_PROMPT,
)
from tests.unit.guide.support import full_guide, operator_server

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "/v1/applications/{application_id}/"
# The four tools whose field-by-field documentation moved to `tool:<name>`.
SHORTENED = (
    "mission_command_send",
    "coordinator_inbox_command",
    "mission_run_fork",
    "mission_governed_prepare",
)
# `tools/list` in tokens (characters of the JSON divided by four). Before the guide: 39 tools,
# 11,106. With it: two more tools and four shortened descriptions. The listing may only
# shrink from here. The owner's target is 9,000 (`scripts/consumer_surface_eval.py` checks
# it); what is left above it is every tool's bare `outputSchema` and empty `_meta`, the other
# tools' descriptions and the request schemas the listing types.
LISTING_TOKENS_BEFORE = 11_106
LISTING_TOKENS_CEILING = 10_450
_TOOL_WORD = re.compile(r"\b(mission_[a-z_]+|coordinator_inbox_[a-z_]+|selection_check)\b")


async def _tools() -> dict[str, Any]:
    async with Client(operator_server()) as client:
        return {tool.name: tool for tool in await client.list_tools()}


def _cli_parsers() -> dict[tuple[str, ...], argparse.ArgumentParser]:
    """Every `missionctl` path with its parser: `("mission", "compile")`, `("guide",)` ..."""

    found: dict[tuple[str, ...], argparse.ArgumentParser] = {}

    def walk(parser: argparse.ArgumentParser, prefix: tuple[str, ...]) -> None:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    found[(*prefix, name)] = child
                    walk(child, (*prefix, name))

    walk(build_parser(), ())
    return found


def _cli_call(call: str) -> tuple[tuple[str, ...], list[str]]:
    """A `missionctl` call's command path and the flags it uses."""

    words = call.split()
    assert words[0] == "missionctl", call
    path: list[str] = []
    for word in words[1:]:
        if not re.fullmatch(r"[a-z][a-z-]*", word):
            break
        path.append(word)
    return tuple(path), [word for word in words if word.startswith("--")]


def _routes() -> set[tuple[str, str]]:
    app = FastAPI()
    for router in (
        mission_router,
        catalog_router,
        lanes_router,
        models_router,
        selection_router,
        guide_router,
        transcript_router,
        cognition_points_router,
        chains_router,
        missions_router,
        human_tasks_router,
        coordinator_inbox_router,
        output_inspection_router,
    ):
        app.include_router(router)
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def _untyped_objects(schema: dict[str, Any]) -> list[str]:
    """Top-level arguments published as a bare object (no properties, nothing closed)."""

    found = []
    for name, prop in schema.get("properties", {}).items():
        for variant in (prop, *prop.get("anyOf", [])):
            if (
                variant.get("type") == "object"
                and "properties" not in variant
                and "$ref" not in variant
                and variant.get("additionalProperties", True) is True
            ):
                found.append(name)
                break
    return found


# -- the operations a page names -----------------------------------------------------------------


def test_every_page_names_only_registered_operations() -> None:
    for page_id in (INDEX, *TOPIC_IDS):
        named = operations_in(load_page("pages", page_id).body)
        assert not [name for name in named if name not in OPERATIONS], page_id
    with pytest.raises(UnknownOperation):
        render_operation("teleport", "mcp")
    # Every registered operation is used, so the registry holds no dead vocabulary.
    used = {
        name
        for page_id in (INDEX, *TOPIC_IDS)
        for name in operations_in(load_page("pages", page_id).body)
    }
    assert used == set(OPERATIONS)


async def test_every_mcp_call_is_a_tool_of_the_operator_server() -> None:
    tools = await _tools()
    for name, operation in OPERATIONS.items():
        tool_name = re.match(r"[a-z_]+", operation.mcp)
        assert tool_name is not None and tool_name.group() in tools, (name, operation.mcp)
        properties = tools[tool_name.group()].inputSchema["properties"]
        # A call written with arguments uses arguments the tool takes.
        for argument in re.findall(r"(\w+)=", operation.mcp):
            assert argument in properties, (name, argument)


async def test_an_agent_with_only_the_mcp_server_can_do_every_operation() -> None:
    tools = await _tools()
    for name in OPERATIONS:
        rendered = render_operation(name, "mcp")
        assert "no MCP tool" not in rendered and rendered.strip("`").split("(")[0] in tools, name


def test_every_cli_call_is_in_the_argparse_tree() -> None:
    parsers = _cli_parsers()
    named = 0
    for name, operation in OPERATIONS.items():
        if operation.cli is None:
            continue
        named += 1
        path, flags = _cli_call(operation.cli)
        assert path in parsers, (name, operation.cli)
        accepted = {option for action in parsers[path]._actions for option in action.option_strings}
        assert not [flag for flag in flags if flag not in accepted], (name, operation.cli)
    assert named > 30
    assert ("guide",) in parsers and ("describe",) in parsers


def test_every_route_is_mounted() -> None:
    routes = _routes()
    for name, operation in OPERATIONS.items():
        if operation.http is None:
            continue
        method, path = operation.http.split(" ", 2)[:2]
        assert (method, PREFIX + path.split("?")[0]) in routes, (name, operation.http)
    api = (ROOT / "src" / "mission_control" / "bootstrap" / "api.py").read_text(encoding="utf-8")
    assert "application.include_router(guide_router)" in api
    assert "application.state.mission_control_guides[key] = compose_guide(" in api


async def test_rendered_pages_name_only_real_tools_and_commands() -> None:
    """The second net: whatever a page says in prose, a tool-shaped or command-shaped word in
    it is a real one."""

    tools = await _tools()
    parsers = _cli_parsers()
    guide = full_guide()
    for page_id in (INDEX, *TOPIC_IDS):
        mcp = (await guide.topic(page_id, "mcp")).markdown
        assert not [word for word in _TOOL_WORD.findall(mcp) if word not in tools], page_id
        cli = (await guide.topic(page_id, "cli")).markdown
        for call in re.findall(r"`(missionctl [^`]+)`", cli):
            assert _cli_call(call)[0] in parsers, (page_id, call)
        for surface in SURFACES:
            assert "{op:" not in (await guide.topic(page_id, surface)).markdown


# -- the moved tool documentation ----------------------------------------------------------------


async def test_every_documented_tool_exists_and_every_bare_object_is_documented() -> None:
    tools = await _tools()

    assert not [name for name in TOOL_DOCS if name not in tools]
    for name, tool in tools.items():
        bare = _untyped_objects(tool.inputSchema)
        if bare:
            # The listing does not type the object: `tool:<name>` must return its shape.
            assert name in TOOL_DOCS, (name, bare)
            argument = TOOL_DOCS[name].argument
            assert argument is None or argument in bare, (name, argument, bare)
    for name in TOOL_DOCS:
        notes = load_page("tools", name).body
        assert not [word for word in _TOOL_WORD.findall(notes) if word not in tools], name


async def test_the_shortened_descriptions_point_at_their_full_shape() -> None:
    tools = await _tools()
    for name in SHORTENED:
        description = (tools[name].description or "").strip()
        assert len(description.splitlines()) <= 8, (name, len(description.splitlines()))
        assert f"mission_describe('tool:{name}')" in description, name
        assert "Example" in description, name
    for name in tools:
        assert (tools[name].description or "").strip(), name


async def test_the_guide_tools_resources_and_prompt_are_on_the_operator_server() -> None:
    async with Client(operator_server()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        resources = {str(resource.uri): resource for resource in await client.list_resources()}
        prompts = {prompt.name for prompt in await client.list_prompts()}

    assert "Call this first" in (tools[GUIDE_TOOL].description or "")
    assert all(topic in (tools[GUIDE_TOOL].description or "") for topic in TOPIC_IDS)
    assert tools[GUIDE_TOOL].inputSchema.get("required", []) == []
    assert tools[DESCRIBE_TOOL].inputSchema["required"] == ["ref"]
    assert {f"{GUIDE_RESOURCE_PREFIX}{name}" for name in (INDEX, *TOPIC_IDS)} <= set(resources)
    assert resources[f"{GUIDE_RESOURCE_PREFIX}interview"].mimeType == "text/markdown"
    assert INTERVIEW_PROMPT in prompts


async def test_the_tool_listing_only_shrinks() -> None:
    tools = await _tools()
    listing = [
        tool.model_dump(mode="json", exclude_none=True, by_alias=True) for tool in tools.values()
    ]
    tokens = sum(len(json.dumps(item)) for item in listing) // 4

    assert len(tools) == 41
    assert tokens <= LISTING_TOKENS_CEILING < LISTING_TOKENS_BEFORE, tokens
