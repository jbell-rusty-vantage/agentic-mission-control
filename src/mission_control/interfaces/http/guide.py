"""Guide routes: how to use this server, who the caller is, and everything about one thing.

`GET /v1/applications/{app}/guide` is the start page (who the caller is, the jobs in order, the
topic and calls for each) and `GET .../guide/{topic}` one topic, each as Markdown inside
`mc.guide.v1`; `surface` chooses the vocabulary its calls are written in (`http` routes by
default, `cli` for `missionctl`, `mcp` for the MCP tools). `GET .../describe?ref=` answers
`mc.describe.v1` for `lane:<profile>`, `model:<profile>`, `feature:<id>`, `tool:<name>`,
`template:<id>`, `sandbox:<profile>`, `manifest`, `manifest:<section>` or a Capability Pin; an
answer that is prose carries `markdown` beside `data`. These need `catalog.read`, launch nothing
and write nothing; the handler is `application/guide/service.py`, the same one behind
`mission_guide` and `mission_describe`.

A request that prefers `text/markdown` (`Accept: text/markdown`) gets the page itself, or the
describe answer as Markdown, with media type `text/markdown`; a refusal stays JSON.

`GET .../whoami` answers `mc.whoami.v1` from the verified principal and its operator grant: the
actor, tenant, permissions, sponsorship and approval refs, the reviewer names it resolves Human
Tasks as, and what this server composed. It needs an authenticated principal of the
application and no further permission: it reads only the caller's own grant.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from mission_control.application.guide.operations import Surface
from mission_control.application.guide.service import (
    DescribeResult,
    GuidePage,
    GuideRefused,
    GuideService,
    describe_markdown,
)
from mission_control.application.guide.whoami import PrincipalFacts, WhoAmI
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
    principal_request_scope,
)

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["guide"])
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
# `app.state` attribute: the operator MCP server's tools (`Mapping[str, ToolListing]`), set by
# the API once it has built that server.
TOOL_LISTING_STATE = "mission_control_tool_listing"
MARKDOWN: Final = "text/markdown"
_STATUS = {"unknown_topic": 404, "unknown_ref": 422, "not_found": 404, "unavailable": 503}
_CODES = {
    "unknown_topic": "guide_topic_unknown",
    "unknown_ref": "describe_ref_unknown",
    "not_found": "describe_not_found",
    "unavailable": "catalog_unavailable",
}


def _composed(application_id: str, request: Request, principal: MissionPrincipal) -> GuideService:
    guide = getattr(request.app.state, "mission_control_guides", {}).get(
        (principal.installation_id, application_id, principal.tenant_id)
    )
    if not isinstance(guide, GuideService):
        raise HTTPException(503, detail={"code": "guide_unavailable"})
    return guide


def guide_service(application_id: str, request: Request, principal: Principal) -> GuideService:
    authorize_application(application_id, request, principal)
    if "catalog.read" not in principal.actor.permissions:
        raise HTTPException(403, detail={"code": "catalog_permission_denied"})
    return _composed(application_id, request, principal)


def identity_service(application_id: str, request: Request, principal: Principal) -> GuideService:
    """The guide of the caller's tenant for `whoami`: any authenticated principal of the
    application reads its own grant."""

    authorize_application(application_id, request, principal)
    return _composed(application_id, request, principal)


Guide = Annotated[GuideService, Depends(guide_service)]
Identity = Annotated[GuideService, Depends(identity_service)]
PageSurface = Annotated[Surface, Query()]


def refusal(refused: GuideRefused) -> HTTPException:
    """The typed refusal: its code, its message and what would have been accepted."""

    return HTTPException(
        _STATUS[refused.code],
        detail={
            "code": _CODES[refused.code],
            "message": str(refused),
            "valid": list(refused.valid),
        },
    )


def prefers_markdown(accept: str | None) -> bool:
    """Whether the `Accept` header ranks `text/markdown` above `application/json` (the first
    listed wins a tie; a header without `text/markdown` keeps JSON)."""

    ranked: dict[str, tuple[float, int]] = {}
    for position, item in enumerate((accept or "").split(",")):
        media, *parameters = (part.strip() for part in item.split(";"))
        quality = 1.0
        for parameter in parameters:
            name, _, value = parameter.partition("=")
            if name.strip() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        ranked.setdefault(media.lower(), (quality, position))
    markdown = ranked.get(MARKDOWN)
    if markdown is None or markdown[0] <= 0:
        return False
    json_rank = ranked.get("application/json")
    if json_rank is None:
        return True
    return (markdown[0], -markdown[1]) > (json_rank[0], -json_rank[1])


def _markdown(text: str) -> Response:
    return Response(content=text, media_type=f"{MARKDOWN}; charset=utf-8")


@router.get("/guide", response_model=GuidePage)
async def index(guide: Guide, request: Request, surface: PageSurface = "http") -> Any:
    page = await guide.index(surface)
    return _markdown(page.markdown) if prefers_markdown(request.headers.get("accept")) else page


@router.get("/guide/{topic}", response_model=GuidePage)
async def topic(topic: str, guide: Guide, request: Request, surface: PageSurface = "http") -> Any:
    try:
        page = await guide.topic(topic, surface)
    except GuideRefused as refused:
        raise refusal(refused) from None
    return _markdown(page.markdown) if prefers_markdown(request.headers.get("accept")) else page


@router.get("/describe", response_model=DescribeResult)
async def describe(
    ref: Annotated[str, Query(min_length=1, max_length=512)], guide: Guide, request: Request
) -> Any:
    # `tool:<name>` answers from the listing of the operator MCP server this API mounts.
    tools = getattr(request.app.state, TOOL_LISTING_STATE, None)
    try:
        result = await guide.describe(ref, tools=tools)
    except GuideRefused as refused:
        raise refusal(refused) from None
    if prefers_markdown(request.headers.get("accept")):
        return _markdown(describe_markdown(result))
    return result


@router.get("/whoami", response_model=WhoAmI)
async def whoami(guide: Identity, principal: Principal) -> WhoAmI:
    return guide.whoami(principal_facts(principal))


def principal_facts(principal: MissionPrincipal) -> PrincipalFacts:
    """The verified HTTP principal as `whoami` reads it."""

    return PrincipalFacts(
        actor_id=principal.actor.actor_id,
        installation_id=str(principal.installation_id),
        application_id=principal.application_id,
        tenant_id=str(principal.tenant_id),
        request_scope=principal_request_scope(principal),
        permissions=frozenset(principal.actor.permissions),
        authority_refs=frozenset(principal.actor.authority_refs),
        sponsorship_refs=principal.sponsorship_refs,
        approval_refs=principal.approval_refs,
    )


__all__ = [
    "TOOL_LISTING_STATE",
    "guide_service",
    "prefers_markdown",
    "principal_facts",
    "refusal",
    "router",
]
