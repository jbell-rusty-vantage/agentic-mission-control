"""Guide routes: how to use this server, and everything about one thing.

`GET /v1/applications/{app}/guide` is the start page (who the caller is, the jobs in order, the
topic and calls for each) and `GET .../guide/{topic}` one topic, each as Markdown inside
`mc.guide.v1`; `surface` chooses the vocabulary its calls are written in (`http` routes by
default, `cli` for `missionctl`, `mcp` for the MCP tools). `GET .../describe?ref=` answers
`mc.describe.v1` for `lane:<profile>`, `model:<profile>`, `feature:<id>`, `tool:<name>` or a
Capability Pin. All need `catalog.read`, launch nothing and write nothing; the handler is
`application/guide/service.py`, the same one behind `mission_guide` and `mission_describe`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from mission_control.application.guide.operations import Surface
from mission_control.application.guide.service import (
    DescribeResult,
    GuidePage,
    GuideRefused,
    GuideService,
)
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
)

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["guide"])
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
_STATUS = {"unknown_topic": 404, "unknown_ref": 422, "not_found": 404, "unavailable": 503}
_CODES = {
    "unknown_topic": "guide_topic_unknown",
    "unknown_ref": "describe_ref_unknown",
    "not_found": "describe_not_found",
    "unavailable": "catalog_unavailable",
}


def guide_service(application_id: str, request: Request, principal: Principal) -> GuideService:
    authorize_application(application_id, request, principal)
    if "catalog.read" not in principal.actor.permissions:
        raise HTTPException(403, detail={"code": "catalog_permission_denied"})
    guide = getattr(request.app.state, "mission_control_guides", {}).get(
        (principal.installation_id, application_id, principal.tenant_id)
    )
    if not isinstance(guide, GuideService):
        raise HTTPException(503, detail={"code": "guide_unavailable"})
    return guide


Guide = Annotated[GuideService, Depends(guide_service)]
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


@router.get("/guide", response_model=GuidePage)
async def index(guide: Guide, surface: PageSurface = "http") -> GuidePage:
    return await guide.index(surface)


@router.get("/guide/{topic}", response_model=GuidePage)
async def topic(topic: str, guide: Guide, surface: PageSurface = "http") -> GuidePage:
    try:
        return await guide.topic(topic, surface)
    except GuideRefused as refused:
        raise refusal(refused) from None


@router.get("/describe", response_model=DescribeResult)
async def describe(
    ref: Annotated[str, Query(min_length=1, max_length=512)], guide: Guide
) -> DescribeResult:
    try:
        return await guide.describe(ref)
    except GuideRefused as refused:
        raise refusal(refused) from None
