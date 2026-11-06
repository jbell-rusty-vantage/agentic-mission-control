"""Operator review of a KS use decision on the operator MCP (W1 D2; parity with HTTP).

``knowledge_review(run_id, request)`` takes the ``POST /runs/{run_id}/knowledge-reviews`` body
and answers the same document, through the one ``KnowledgeReviewService`` of the principal's
verified tenant scope. Authorization is the service's (``knowledge.review``; never the run's
producer or evaluators). Only the operator server registers it: a coordinator never reviews.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from fastmcp import Context, FastMCP

from mission_control.application.knowledge.review import (
    KnowledgeReviewRequest,
    KnowledgeReviewService,
    ReviewRejected,
)
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.coordinator.errors import CoordinatorDomainError, CoordinatorErrorCode
from mission_control.domain.policies.contracts import ActorContext

KNOWLEDGE_REVIEW_TOOL = "knowledge_review"
_CODES: dict[str, CoordinatorErrorCode] = {
    "unauthorized_review": CoordinatorErrorCode.FORBIDDEN,
    "invalid": CoordinatorErrorCode.INVALID_ARGUMENT,
    "not_found": CoordinatorErrorCode.NOT_FOUND,
    "decision_not_in_run": CoordinatorErrorCode.CONFLICT,
    "review_refused": CoordinatorErrorCode.CONFLICT,
    "review_unavailable": CoordinatorErrorCode.DEPENDENCY_UNAVAILABLE,
}


class ReviewPrincipal(Protocol):
    @property
    def actor_id(self) -> str: ...

    @property
    def permissions(self) -> frozenset[str]: ...

    @property
    def request_scope(self) -> str: ...


def domain_error(error: ReviewRejected) -> CoordinatorDomainError:
    details: dict[str, Any] = {"code": error.code}
    if error.ks_code is not None:
        details["ks_code"] = error.ks_code
    return CoordinatorDomainError(
        code=_CODES.get(error.code, CoordinatorErrorCode.INVALID_ARGUMENT),
        message=str(error),
        details=details,
    )


class ScopedKnowledgeReviews:
    """Selects the review service of the principal's verified tenant scope."""

    def __init__(self, services: Mapping[str, KnowledgeReviewService]) -> None:
        self._services = dict(services)

    def service(self, principal: ReviewPrincipal) -> KnowledgeReviewService:
        scope = principal.request_scope
        try:
            parse_request_scope(scope)
        except ValueError:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN,
                message="knowledge review needs a canonical tenant request scope",
            ) from None
        service = self._services.get(scope)
        if service is None:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN,
                message="no knowledge review service for scope",
            )
        return service

    async def review(
        self, principal: ReviewPrincipal, *, run_id: str, request: Mapping[str, Any]
    ) -> dict[str, object]:
        body = KnowledgeReviewRequest.model_validate(dict(request))
        actor = ActorContext(
            actor_id=principal.actor_id, permissions=frozenset(principal.permissions)
        )
        try:
            return await self.service(principal).review(run_id, body, actor)
        except ReviewRejected as error:
            raise domain_error(error) from None


def register_knowledge_review_tools(
    server: FastMCP,
    reviews: ScopedKnowledgeReviews,
    principals: Any,
    *,
    call: Callable[..., Awaitable[dict[str, object]]],
) -> None:
    """Register ``knowledge_review``; ``call`` wraps results in the MCP envelope."""

    @server.tool(name=KNOWLEDGE_REVIEW_TOOL)
    async def knowledge_review(
        run_id: str, request: dict[str, Any], context: Context
    ) -> dict[str, object]:
        async def invoke(principal: Any) -> object:
            return await reviews.review(principal, run_id=run_id, request=request)

        return await call(context, principals, invoke)


__all__ = [
    "KNOWLEDGE_REVIEW_TOOL",
    "ScopedKnowledgeReviews",
    "domain_error",
    "register_knowledge_review_tools",
]
