"""The guide on the coordinator and operator MCP servers.

An agent that has only the MCP server cannot read a skill file, so the server says how it is
used:

- tool `mission_guide(topic)` (read-only; `catalog.read`): the start page, or one topic, as
  `GET /guide` and `GET /guide/{topic}` return it, with every call named as an MCP tool;
- tool `mission_describe(ref)` (read-only; `catalog.read`): everything about one lane, Model
  Profile, feature, tool, mission template, sandbox profile, capability or the Mission Manifest,
  as `GET /describe?ref=` returns it. `tool:<name>` answers for every tool of the server it is
  asked on, from that server's own listing (`server_tool_listing`);
- tool `mission_whoami()` (read-only; any authenticated principal): `mc.whoami.v1`, the
  caller's actor, tenant, permissions, sponsorship and approval refs, the reviewer names it
  resolves Human Tasks as and what this server composed, as `GET /whoami` returns it;
- resources `mc://guide/<topic>`: the same pages as Markdown, one resource per page;
- prompt `interview_before_mission`: the interview page.

A page arrives as Markdown and only as Markdown: the tool result's text content is the page
itself, and its structured content is the envelope without the body (`ok`, the correlation id
and the page's `topic`, `title`, `summary` and `surface`), so a client that shows structured
content never shows the page a second time as an escaped string. The same holds for a describe
answer that is prose (a tool, a template, the manifest reference): its structured content
keeps `ref`, `kind` and `title`. A describe answer that is data (a lane, a model, a
capability, a sandbox profile) and every refusal is the envelope as JSON text, as on every
other tool.

The principal's canonical request scope selects the tenant's guide; nothing here launches.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from mission_control.application.guide.pages import INDEX, TOPIC_IDS, load_page
from mission_control.application.guide.service import GuideRefused, GuideService, ToolListing
from mission_control.application.guide.whoami import PrincipalFacts
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.coordinator.errors import CoordinatorDomainError, CoordinatorErrorCode
from mission_control.interfaces.mcp.mission_tools import (
    MissionToolPrincipal,
    PrincipalResolver,
    scope_of,
)

GUIDE_TOOL: Final = "mission_guide"
DESCRIBE_TOOL: Final = "mission_describe"
WHOAMI_TOOL: Final = "mission_whoami"
# What a Markdown answer's structured content leaves out: the page, and the data it renders.
BODY_FIELDS: Final = frozenset({"markdown", "data"})
GUIDE_RESOURCE_PREFIX: Final = "mc://guide/"
INTERVIEW_PROMPT: Final = "interview_before_mission"
# One permission name on every transport (HTTP, CLI, MCP): `catalog.read`.
READ_GRANTS = frozenset({"catalog.read"})
_CODES: Final[dict[str, CoordinatorErrorCode]] = {
    "unknown_topic": CoordinatorErrorCode.INVALID_ARGUMENT,
    "unknown_ref": CoordinatorErrorCode.INVALID_ARGUMENT,
    "not_found": CoordinatorErrorCode.NOT_FOUND,
    "unavailable": CoordinatorErrorCode.DEPENDENCY_UNAVAILABLE,
}


def guide_error(refused: GuideRefused) -> CoordinatorDomainError:
    """The MCP envelope of a guide refusal: its reason and what would have been accepted."""

    return CoordinatorDomainError(
        _CODES[refused.code],
        str(refused),
        details={"reason": refused.code, "valid": ", ".join(refused.valid)},
    )


async def server_tool_listing(server: FastMCP) -> dict[str, ToolListing]:
    """Every tool of a server as `tool:<name>` describes it: the description and the argument
    schema the server's own `tools/list` publishes."""

    return {
        tool.name: ToolListing(
            name=tool.name,
            description=(tool.description or "").strip(),
            input_schema=dict(tool.parameters),
        )
        for tool in await server.list_tools(run_middleware=False)
    }


def markdown_result(envelope: Mapping[str, object]) -> ToolResult:
    """A guide tool's result. Where the envelope's data carries `markdown`, the text content
    is that Markdown as written and the structured content is the envelope without the body
    (no `markdown`, and no `data` restating it), so an agent reads the page once and never as
    an escaped string. Any other answer, a refusal included, is the envelope as JSON text and
    as structured content, as on every other tool."""

    data = envelope.get("data")
    markdown = data.get("markdown") if isinstance(data, Mapping) else None
    if envelope.get("ok") is not True or not isinstance(markdown, str):
        return ToolResult(
            content=[TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False))],
            structured_content=dict(envelope),
        )
    assert isinstance(data, Mapping)
    header = {key: value for key, value in data.items() if key not in BODY_FIELDS}
    return ToolResult(
        content=[TextContent(type="text", text=markdown)],
        structured_content={**envelope, "data": header},
    )


class ScopedGuide:
    """Selects the guide of the principal's verified tenant scope."""

    def __init__(self, guides: Mapping[str, GuideService]) -> None:
        self._guides = dict(guides)

    def guide(self, principal: MissionToolPrincipal) -> GuideService:
        if not frozenset(principal.permissions) & READ_GRANTS:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN,
                message=f"principal lacks catalog read; {WHOAMI_TOOL} lists what it holds",
                details={"required": ",".join(sorted(READ_GRANTS))},
            )
        return self._scoped(principal)

    def _scoped(self, principal: MissionToolPrincipal) -> GuideService:
        guide = self._guides.get(scope_of(principal, None))
        if guide is None:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message="no guide for scope"
            )
        return guide

    def whoami(self, principal: MissionToolPrincipal) -> dict[str, object]:
        """`mc.whoami.v1` of the verified principal: it reads its own grant, so it needs no
        permission beyond being authenticated for this scope."""

        scope = parse_request_scope(scope_of(principal, None))
        facts = PrincipalFacts(
            actor_id=principal.actor_id,
            installation_id=str(scope.installation_id),
            application_id=scope.application_id,
            tenant_id=str(scope.tenant_id),
            request_scope=principal.request_scope,
            permissions=frozenset(principal.permissions),
            authority_refs=frozenset(getattr(principal, "authority_refs", ())),
            sponsorship_refs=frozenset(getattr(principal, "sponsorship_refs", ())),
            approval_refs=frozenset(getattr(principal, "approval_refs", ())),
        )
        return self._scoped(principal).whoami(facts).model_dump(mode="json")

    async def page(self, principal: MissionToolPrincipal, topic: str | None) -> dict[str, object]:
        guide = self.guide(principal)
        try:
            page = await (guide.index("mcp") if topic is None else guide.topic(topic, "mcp"))
        except GuideRefused as refused:
            raise guide_error(refused) from None
        return page.model_dump(mode="json")

    async def describe(
        self,
        principal: MissionToolPrincipal,
        ref: str,
        *,
        tools: Mapping[str, ToolListing] | None = None,
    ) -> dict[str, object]:
        try:
            result = await self.guide(principal).describe(ref, tools=tools)
        except GuideRefused as refused:
            raise guide_error(refused) from None
        return result.model_dump(mode="json")


def register_guide_tools(
    server: FastMCP,
    guides: ScopedGuide,
    principals: PrincipalResolver,
    *,
    call: Any,
) -> None:
    """The two read-only tools, the page resources and the interview prompt; ``call`` wraps
    tool results in the MCP envelope."""

    # The server's own tools, listed once: a server's tools do not change after it is built.
    listed: dict[str, ToolListing] = {}

    async def listing() -> dict[str, ToolListing]:
        if not listed:
            listed.update(await server_tool_listing(server))
        return listed

    @server.tool(
        name=GUIDE_TOOL,
        annotations={"readOnlyHint": True},
        description=(
            "Call this first. How to use this server: with no `topic` the start page (the "
            "jobs in order and the tools for each), else one page: "
            f"{', '.join(TOPIC_IDS)}."
        ),
    )
    async def mission_guide(context: Context, topic: str | None = None) -> ToolResult:
        async def invoke(principal: Any) -> object:
            return await guides.page(principal, topic)

        return markdown_result(await call(context, principals, invoke))

    @server.tool(name=DESCRIBE_TOOL, annotations={"readOnlyHint": True})
    async def mission_describe(ref: str, context: Context) -> ToolResult:
        """Everything about one thing. `ref`: `lane:<profile>` (controls, delivery semantics,
        time travel), `model:<profile>`, `feature:<id>`, `tool:<name>` (any tool's arguments
        and notes), `template:<id>`, `manifest` (every field), `sandbox:<profile>` or a
        mission_search hit's `ref`."""

        async def invoke(principal: Any) -> object:
            return await guides.describe(principal, ref, tools=await listing())

        return markdown_result(await call(context, principals, invoke))

    @server.tool(name=WHOAMI_TOOL, annotations={"readOnlyHint": True})
    async def mission_whoami(context: Context) -> dict[str, object]:
        """Who you are on this server: your `actor_id`, tenant, `permissions`, the
        `sponsorship_refs` and `approval_refs` you hold (a fork names one sponsorship),
        `reviews_as` (the reviewer names you can resolve a Human Task as) and `server` (what
        this server cannot do yet, with the prerequisite)."""

        async def invoke(principal: Any) -> object:
            return guides.whoami(principal)

        result: dict[str, object] = await call(context, principals, invoke)
        return result

    for page_id in (INDEX, *TOPIC_IDS):
        _register_page_resource(server, guides, principals, page_id)

    @server.prompt(
        name=INTERVIEW_PROMPT,
        description="How to interview the user before a mission and map the brief to a manifest.",
    )
    async def interview_before_mission(context: Context) -> str:
        principal = await principals.resolve(context)
        return str((await guides.page(principal, "interview"))["markdown"])


def _register_page_resource(
    server: FastMCP, guides: ScopedGuide, principals: PrincipalResolver, page_id: str
) -> None:
    source = load_page("pages", page_id)

    @server.resource(
        f"{GUIDE_RESOURCE_PREFIX}{page_id}",
        name=f"guide_{page_id}",
        title=source.title,
        description=source.summary,
        mime_type="text/markdown",
    )
    async def guide_page(context: Context) -> str:
        principal = await principals.resolve(context)
        page = await guides.page(principal, None if page_id == INDEX else page_id)
        return str(page["markdown"])


__all__ = [
    "DESCRIBE_TOOL",
    "GUIDE_RESOURCE_PREFIX",
    "GUIDE_TOOL",
    "INTERVIEW_PROMPT",
    "WHOAMI_TOOL",
    "ScopedGuide",
    "guide_error",
    "markdown_result",
    "register_guide_tools",
    "server_tool_listing",
]
