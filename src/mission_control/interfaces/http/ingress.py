"""Signal Ingress routes `/v1/ingress/{app}/...` (SPEC-10 section 2; ADR-0045).

The same router serves the public edge (`create_ingress_app`, the slim app the Vercel project
vendors, MO-74) and the worker's loopback listener (`create_hook_callback_app` mounts it beside
the Kernel Hook callback), so a local lane and a cloud VM reach the same handlers. Each route
reads the raw body under a hard cap before anything parses it, then makes one service call.
Rejections are typed (`{"code": ...}`); a credential or signature is never echoed.

| Route | Reply |
| --- | --- |
| `POST signals` | 202 `{accepted, duplicates}` |
| `POST signals?gate=1` | 200 `{decision, reason}` |
| `POST artifacts:prepare` / `artifacts:commit` | 200 upload slot / 202 `{ingress_id}` |
| `POST provider/anthropic`, `provider/openai`, `provider/cursor/{run_ref}`, `github` | 204 |
| `POST missions:request` / `GET missions:request/{id}` | 202 `{request_id}` / 200 status |

A provider webhook answers 204 for a repeated delivery id as well, recording nothing, so the
provider stops retrying; a forged or stale delivery is a typed 401.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from mission_control.application.signals.contracts import IngressRejected
from mission_control.application.signals.service import SignalIngressService, rejection

INGRESS_PREFIX = "/v1/ingress/{application_id}"
router = APIRouter(prefix=INGRESS_PREFIX, tags=["ingress"])


def _service(request: Request, application_id: str) -> SignalIngressService:
    services = getattr(request.app.state, "mission_control_ingress", None)
    service = services.get(application_id) if isinstance(services, Mapping) else None
    if not isinstance(service, SignalIngressService):
        raise HTTPException(404, detail={"code": "unknown_application"})
    return service


async def _body(request: Request, limit: int) -> bytes:
    """The raw body, refused as soon as it exceeds `limit` bytes."""

    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise rejection("payload_too_large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise rejection("payload_too_large")
    return bytes(body)


def _http(rejected: IngressRejected) -> HTTPException:
    return HTTPException(rejected.status_code, detail={"code": rejected.code})


@router.post("/signals", status_code=202)
async def signals(application_id: str, request: Request, response: Response) -> dict[str, Any]:
    service = _service(request, application_id)
    gate = request.query_params.get("gate") == "1"
    limits = service.limits
    try:
        body = await _body(request, limits.max_signal_bytes if gate else limits.max_batch_bytes)
        if gate:
            answer = await service.gate(body, request.headers)
            response.status_code = 200
            return answer.model_dump(mode="json")
        receipt = await service.signals(body, request.headers)
    except IngressRejected as rejected:
        raise _http(rejected) from None
    return receipt.model_dump(mode="json")


@router.post("/artifacts:prepare")
async def prepare_artifact(application_id: str, request: Request) -> dict[str, Any]:
    service = _service(request, application_id)
    try:
        body = await _body(request, service.limits.max_signal_bytes)
        slot = await service.prepare_artifact(body, request.headers)
    except IngressRejected as rejected:
        raise _http(rejected) from None
    return slot.model_dump(mode="json")


@router.post("/artifacts:commit", status_code=202)
async def commit_artifact(application_id: str, request: Request) -> dict[str, str]:
    service = _service(request, application_id)
    try:
        body = await _body(request, service.limits.max_signal_bytes)
        ingress_id = await service.commit_artifact(body, request.headers)
    except IngressRejected as rejected:
        raise _http(rejected) from None
    return {"ingress_id": str(ingress_id)}


async def _webhook(
    application_id: str, provider: str, request: Request, route_ref: str | None = None
) -> Response:
    service = _service(request, application_id)
    try:
        body = await _body(request, service.limits.max_webhook_bytes)
        await service.webhook(provider, body, request.headers, route_ref=route_ref)
    except IngressRejected as rejected:
        raise _http(rejected) from None
    return Response(status_code=204)


@router.post("/provider/cursor/{run_ref}", status_code=204)
async def cursor_webhook(application_id: str, run_ref: str, request: Request) -> Response:
    return await _webhook(application_id, "cursor", request, run_ref)


@router.post("/provider/{provider}", status_code=204)
async def provider_webhook(application_id: str, provider: str, request: Request) -> Response:
    if provider == "cursor":
        raise HTTPException(404, detail={"code": "unknown_provider"})
    return await _webhook(application_id, provider, request)


@router.post("/github", status_code=204)
async def github_webhook(application_id: str, request: Request) -> Response:
    return await _webhook(application_id, "github", request)


@router.post("/missions:request", status_code=202)
async def request_mission(application_id: str, request: Request) -> dict[str, str]:
    service = _service(request, application_id)
    try:
        body = await _body(request, service.limits.max_signal_bytes)
        request_id = await service.request_mission(body, request.headers)
    except IngressRejected as rejected:
        raise _http(rejected) from None
    return {"request_id": str(request_id)}


@router.get("/missions:request/{request_id}")
async def mission_request_status(
    application_id: str, request_id: UUID, request: Request
) -> dict[str, Any]:
    service = _service(request, application_id)
    try:
        status = await service.mission_request_status(request_id, request.headers)
    except IngressRejected as rejected:
        raise _http(rejected) from None
    return status.model_dump(mode="json", exclude_none=True)


def mount_ingress(app: FastAPI, services: Iterable[SignalIngressService]) -> None:
    """Serve the ingress routes on `app` for one service per application."""

    by_application = {service.application_id: service for service in services}
    app.state.mission_control_ingress = by_application
    app.include_router(router)


def create_ingress_app(services: Iterable[SignalIngressService]) -> FastAPI:
    """The public edge: the ingress routes and a process-only liveness probe, nothing else."""

    app = FastAPI(
        title="Mission Control Signal Ingress",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )
    mount_ingress(app, services)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    return app


__all__ = ["INGRESS_PREFIX", "create_ingress_app", "mount_ingress", "router"]
