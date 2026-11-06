"""Exact output, fulfillment and transfer inspection over HTTP (WI-19, OUTPUT-CONTRACTS §3/§12).

Read-only routes over the tenant's ``OutputInspectionService``; ``missionctl outputs`` and the
operator MCP call the same handlers. Every route needs ``workflow_run.read``; a run of another
tenant reads as absent. Pages carry an opaque cursor the service issued.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from mission_control.application.outputs.inspection import (
    InspectionRejected,
    OutputInspectionService,
)
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
    principal_request_scope,
)

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["output-inspection"])
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
REGISTRY = "mission_control_output_inspection_services"
STATUS = {"unauthorized": 403, "not_found": 404, "invalid": 422}


def get_output_inspection_service(
    application_id: str, request: Request, principal: Principal
) -> OutputInspectionService:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, REGISTRY, {})
    service = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(service, OutputInspectionService):
        raise HTTPException(status_code=503, detail={"code": "inspection_unavailable"})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service


Service = Annotated[OutputInspectionService, Depends(get_output_inspection_service)]


def _error(exc: InspectionRejected) -> HTTPException:
    return HTTPException(
        status_code=STATUS.get(exc.code, 422), detail={"code": exc.code, "message": str(exc)}
    )


@router.get("/runs/{run_id}/outputs")
async def run_outputs(run_id: str, principal: Principal, service: Service) -> dict[str, Any]:
    """Promises, accepted heads, fulfillment, assessments, plans and actionable items."""

    try:
        view = await service.outputs(run_id, principal.actor)
    except InspectionRejected as exc:
        raise _error(exc) from None
    return {"application_id": principal.application_id, **view.model_dump(mode="json")}


@router.get("/runs/{run_id}/outputs/{obligation_key}/revisions")
async def output_revisions(
    run_id: str,
    obligation_key: str,
    principal: Principal,
    service: Service,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    try:
        page = await service.revisions(
            run_id, obligation_key, principal.actor, cursor=cursor, limit=limit
        )
    except InspectionRejected as exc:
        raise _error(exc) from None
    return {"application_id": principal.application_id, **page.model_dump(mode="json")}


@router.get("/runs/{run_id}/output-events")
async def output_events(
    run_id: str,
    principal: Principal,
    service: Service,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    try:
        page = await service.events(run_id, principal.actor, cursor=cursor, limit=limit)
    except InspectionRejected as exc:
        raise _error(exc) from None
    return {"application_id": principal.application_id, **page.model_dump(mode="json")}


@router.get("/runs/{run_id}/transfer-plans")
async def transfer_plans(run_id: str, principal: Principal, service: Service) -> dict[str, Any]:
    try:
        plans = await service.transfer_plans(run_id, principal.actor)
    except InspectionRejected as exc:
        raise _error(exc) from None
    return {
        "application_id": principal.application_id,
        "run_id": run_id,
        "transfer_plans": [item.model_dump(mode="json") for item in plans],
    }


@router.get("/transfer-plans/{plan_id}")
async def transfer_plan(plan_id: str, principal: Principal, service: Service) -> dict[str, Any]:
    try:
        detail = await service.transfer_plan(plan_id, principal.actor)
    except InspectionRejected as exc:
        raise _error(exc) from None
    return {"application_id": principal.application_id, **detail.model_dump(mode="json")}


__all__ = ["REGISTRY", "get_output_inspection_service", "router"]
