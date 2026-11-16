"""The guide on the coordinator and operator MCP servers.

An agent that has only the MCP server cannot read a skill file, so the server says how it is
used:

- tool `mission_guide(topic)` (read-only; `catalog.read`): the start page, or one topic, as
  `GET /guide` and `GET /guide/{topic}` return it, with every call named as an MCP tool;
- tool `mission_describe(ref)` (read-only; `catalog.read`): everything about one lane, Model
  Profile, feature, tool request or capability, as `GET /describe?ref=` returns it;
- resources `mc://guide/<topic>`: the same pages as Markdown, one resource per page;
- prompt `interview_before_mission`: the interview page.

The principal's canonical request scope selects the tenant's guide; nothing here launches.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from fastmcp import Context, FastMCP

from mission_control.application.guide.pages import INDEX, TOPIC_IDS, load_page
from mission_control.application.guide.service import GuideRefused, GuideService
from mission_control.domain.coordinator.errors import CoordinatorDomainError, CoordinatorErrorCode
from mission_control.interfaces.mcp.mission_tools import (
    MissionToolPrincipal,
    PrincipalResolver,
    scope_of,
)

GUIDE_TOOL: Final = "mission_guide"
DESCRIBE_TOOL: Final = "mission_describe"
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


class ScopedGuide:
    """Selects the guide of the principal's verified tenant scope."""

    def __init__(self, guides: Mapping[str, GuideService]) -> None:
        self._guides = dict(guides)

    def guide(self, principal: MissionToolPrincipal) -> GuideService:
        if not frozenset(principal.permissions) & READ_GRANTS:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message="principal lacks catalog read"
            )
        guide = self._guides.get(scope_of(principal, None))
        if guide is None:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message="no guide for scope"
            )
        return guide

    async def page(self, principal: MissionToolPrincipal, topic: str | None) -> dict[str, object]:
        guide = self.guide(principal)
        try:
            page = await (guide.index("mcp") if topic is None else guide.topic(topic, "mcp"))
        except GuideRefused as refused:
            raise guide_error(refused) from None
        return page.model_dump(mode="json")

    async def describe(self, principal: MissionToolPrincipal, ref: str) -> dict[str, object]:
        try:
            result = await self.guide(principal).describe(ref)
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

    @server.tool(
        name=GUIDE_TOOL,
        annotations={"readOnlyHint": True},
        description=(
            "Call this first. How to use this server: with no `topic` the start page (the "
            "jobs in order and the tools for each), else one page: "
            f"{', '.join(TOPIC_IDS)}."
        ),
    )
    async def mission_guide(context: Context, topic: str | None = None) -> dict[str, object]:
        async def invoke(principal: Any) -> object:
            return await guides.page(principal, topic)

        return await call(context, principals, invoke)

    @server.tool(name=DESCRIBE_TOOL, annotations={"readOnlyHint": True})
    async def mission_describe(ref: str, context: Context) -> dict[str, object]:
        """Everything about one thing. `ref`: `lane:<profile>` (controls, delivery semantics,
        time travel), `model:<profile>`, `feature:<id>`, `tool:<name>` (a tool's full request
        shape) or a mission_search hit's `ref` (one capability)."""

        async def invoke(principal: Any) -> object:
            return await guides.describe(principal, ref)

        return await call(context, principals, invoke)

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
    "ScopedGuide",
    "guide_error",
    "register_guide_tools",
]
