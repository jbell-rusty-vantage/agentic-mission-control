"""Operator review of a KS use decision over HTTP (W1 D2; OUTPUT-CONTRACTS §5).

``POST /v1/applications/{application_id}/runs/{run_id}/knowledge-reviews`` relays one exact
review through the tenant's ``KnowledgeReviewService`` (the one KS review path). ``missionctl
knowledge review`` and the operator MCP ``knowledge_review`` tool call the same handler. The
actor needs ``knowledge.review`` and may not be the run's producer or evaluators
(``unauthorized_review``, 403); KS refusals answer 409 with their KS code.

``POST .../runs/{run_id}/evaluator-attempt-resets`` (W1 fix G S2) resets one role's exhausted
evaluator attempts on an exact output revision under the same authorization; a role with no
recorded billed attempt answers 409 ``nothing_to_reset``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from mission_control.application.knowledge.review import (
    EvaluatorAttemptResetRequest,
    KnowledgeReviewRequest,
    KnowledgeReviewService,
    ReviewRejected,
)
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
    principal_request_scope,
    require_strict_json_body,
)

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["knowledge-reviews"])
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
REGISTRY = "mission_control_knowledge_review_services"
STATUS = {
    "unauthorized_review": 403,
    "invalid": 422,
    "not_found": 404,
    "decision_not_in_run": 409,
    "review_refused": 409,
    "review_unavailable": 503,
    "nothing_to_reset": 409,
}


def get_knowledge_review_service(
    application_id: str, request: Request, principal: Principal
) -> KnowledgeReviewService:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, REGISTRY, {})
    service = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(service, KnowledgeReviewService):
        raise HTTPException(status_code=503, detail={"code": "knowledge_review_unavailable"})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service


Service = Annotated[KnowledgeReviewService, Depends(get_knowledge_review_service)]


def rejection(exc: ReviewRejected) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.ks_code is not None:
        detail["ks_code"] = exc.ks_code
    return HTTPException(status_code=STATUS.get(exc.code, 422), detail=detail)


@router.post("/runs/{run_id}/knowledge-reviews", dependencies=[Depends(require_strict_json_body)])
async def review_decision(
    run_id: str, body: KnowledgeReviewRequest, principal: Principal, service: Service
) -> dict[str, Any]:
    """Relay one authorized review of an exact KS use decision; answers KS's successor."""

    try:
        result = await service.review(run_id, body, principal.actor)
    except ReviewRejected as exc:
        raise rejection(exc) from None
    return {"application_id": principal.application_id, **result}


@router.post(
    "/runs/{run_id}/evaluator-attempt-resets",
    dependencies=[Depends(require_strict_json_body)],
)
async def reset_evaluator_attempts(
    run_id: str, body: EvaluatorAttemptResetRequest, principal: Principal, service: Service
) -> dict[str, Any]:
    """Reset one role's exhausted evaluator attempts on an exact revision (audited)."""

    try:
        result = await service.reset_evaluator_attempts(run_id, body, principal.actor)
    except ReviewRejected as exc:
        raise rejection(exc) from None
    return {"application_id": principal.application_id, **result}


__all__ = ["REGISTRY", "get_knowledge_review_service", "rejection", "router"]
