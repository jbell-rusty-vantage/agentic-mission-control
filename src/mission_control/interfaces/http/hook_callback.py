"""Worker-only Kernel Hook callback (SPEC-07 section 5.5; FT-G3).

`POST /v1/applications/{app}/internal/hook-callback` on the worker's loopback listener (bound
to `127.0.0.1` by the worker, never mounted on the public API). The caller is
`.mission/hooks/kernel.py` inside a leased workspace; it authenticates with the task-scoped
bearer token minted for that harness execution and generation. The application in the path
must match the token's scope. Rejections are typed (`missing_task_token`,
`unknown_task_token`, `expired_task_token`, `task_token_scope_mismatch`, `STALE_GENERATION`);
the token value is never logged or echoed.

The loopback app also serves the Signal Ingress routes (`interfaces/http/ingress.py`) when the
worker composes ingress services, so a local lane's signals, gates and uploads reach the same
handlers as a cloud VM's (SPEC-04 section 3); both parse bearers with the same helper.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request

from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackRejected,
    HookCallbackService,
    KernelHookCall,
)
from mission_control.application.signals.service import SignalIngressService
from mission_control.application.signals.verification import bearer_token
from mission_control.interfaces.http.ingress import mount_ingress

HOOK_CALLBACK_PATH = "/v1/applications/{application_id}/internal/hook-callback"
router = APIRouter(tags=["internal"])


def _service(request: Request) -> HookCallbackService:
    service = getattr(request.app.state, "mission_control_hook_callbacks", None)
    if not isinstance(service, HookCallbackService):
        raise HTTPException(503, detail={"code": "hook_callbacks_unavailable"})
    return service


@router.post(HOOK_CALLBACK_PATH)
async def hook_callback(
    application_id: str,
    call: KernelHookCall,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    service = _service(request)
    try:
        result = await service.handle(
            call, bearer_token(authorization), application_id=application_id
        )
    except HookCallbackRejected as rejected:
        raise HTTPException(rejected.status_code, detail={"code": rejected.code}) from None
    return result.model_dump(mode="json", exclude_none=True)


def create_hook_callback_app(
    service: HookCallbackService, *, ingress: Iterable[SignalIngressService] = ()
) -> FastAPI:
    """The loopback app the worker serves: the Kernel Hook callback and, when composed, the
    Signal Ingress routes; nothing else is mounted on it."""

    app = FastAPI(title="Mission Control hook callback", docs_url=None, redoc_url=None)
    app.state.mission_control_hook_callbacks = service
    app.include_router(router)
    services = tuple(ingress)
    if services:
        mount_ingress(app, services)
    return app


__all__ = ["HOOK_CALLBACK_PATH", "create_hook_callback_app", "router"]
