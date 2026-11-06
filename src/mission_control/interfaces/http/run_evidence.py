"""Authenticated retrieval of existing input/result/evidence authorities."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from mission_control.application.missions.retrieval import (
    RunEvidenceInconsistent,
    RunEvidenceService,
)
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.run_evidence import (
    CompletionEvidencePage,
    GoalCompletionEvidencePage,
    RunEvidence,
    RunInputs,
)
from mission_control.domain.policies.errors import RunControlNotFound
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
    principal_request_scope,
)

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["run-evidence"])
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]


def get_run_evidence_service(
    application_id: str, request: Request, principal: Principal
) -> RunEvidenceService:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, "mission_control_evidence_services", {})
    service = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(service, RunEvidenceService):
        raise HTTPException(status_code=503, detail={"code": "run_evidence_unavailable"})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service


Service = Annotated[RunEvidenceService, Depends(get_run_evidence_service)]


@router.get("/runs/{run_id}/goal-completion-evidence", response_model=GoalCompletionEvidencePage)
async def goal_completion_evidence(
    run_id: str,
    principal: Principal,
    service: Service,
    after_verification_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> GoalCompletionEvidencePage:
    try:
        return await service.goal_completion(
            run_id, actor=principal.actor, after=after_verification_id, limit=limit
        )
    except (MissionControlRejected, RunControlNotFound, RunEvidenceInconsistent) as exc:
        raise _error(exc) from None


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, MissionControlRejected):
        return HTTPException(status_code=403, detail={"code": "unauthorized"})
    if isinstance(exc, RunControlNotFound):
        return HTTPException(status_code=404, detail={"code": "resource_not_found"})
    return HTTPException(status_code=409, detail={"code": "run_evidence_inconsistent"})


@router.get("/runs/{run_id}/evidence", response_model=RunEvidence)
async def run_evidence(run_id: str, principal: Principal, service: Service) -> RunEvidence:
    try:
        return await service.get(run_id, actor=principal.actor)
    except (MissionControlRejected, RunControlNotFound, RunEvidenceInconsistent) as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}/inputs", response_model=RunInputs)
async def run_inputs(run_id: str, principal: Principal, service: Service) -> RunInputs:
    try:
        return await service.inputs(run_id, actor=principal.actor)
    except (MissionControlRejected, RunControlNotFound, RunEvidenceInconsistent) as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}/completion-evidence", response_model=CompletionEvidencePage)
async def completion_evidence(
    run_id: str,
    principal: Principal,
    service: Service,
    after_family_version: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> CompletionEvidencePage:
    try:
        return await service.completion(
            run_id,
            actor=principal.actor,
            after_family_version=after_family_version,
            limit=limit,
        )
    except (MissionControlRejected, RunControlNotFound, RunEvidenceInconsistent) as exc:
        raise _error(exc) from None
