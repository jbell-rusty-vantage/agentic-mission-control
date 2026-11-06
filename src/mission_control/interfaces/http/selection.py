"""Selection Workspace routes: one faceted search and one read-only draft check.

`POST /v1/applications/{app}/selection/search` merges Capability Search, the registered lanes,
the Model Catalog, sandbox profiles and Workflow Types into one ranked answer;
`POST .../selection/check` answers whether a draft selection (lane, model profile, family,
data class, capability pins, sandbox profile, Workflow Type) would be admitted, with typed
refusals. Both need `catalog:read`, launch nothing and write nothing; the handler is
`application/selection/workspace.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from mission_control.application.selection.workspace import (
    SelectionCheck,
    SelectionDraft,
    SelectionSearchRequest,
    SelectionSearchResult,
    SelectionWorkspace,
)
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
)

router = APIRouter(prefix="/v1/applications/{application_id}/selection", tags=["selection"])
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]


def selection_workspace(
    application_id: str, request: Request, principal: Principal
) -> SelectionWorkspace:
    authorize_application(application_id, request, principal)
    if "catalog:read" not in principal.actor.permissions:
        raise HTTPException(403, detail={"code": "catalog_permission_denied"})
    workspace = getattr(request.app.state, "mission_control_selection_workspaces", {}).get(
        (principal.installation_id, application_id, principal.tenant_id)
    )
    if not isinstance(workspace, SelectionWorkspace):
        raise HTTPException(503, detail={"code": "selection_unavailable"})
    return workspace


Workspace = Annotated[SelectionWorkspace, Depends(selection_workspace)]


@router.post("/search", response_model=SelectionSearchResult)
async def search(body: SelectionSearchRequest, workspace: Workspace) -> SelectionSearchResult:
    return await workspace.search(body)


@router.post("/check", response_model=SelectionCheck)
async def check(body: SelectionDraft, workspace: Workspace) -> SelectionCheck:
    return await workspace.check(body)
