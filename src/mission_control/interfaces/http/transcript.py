"""Run Transcript over HTTP (SPEC-03, C3).

- `GET /v1/applications/{app}/runs/{run_id}/transcript` returns the materialized
  transcript: JSONL (`application/x-ndjson`, default), a JSON page (`format=json` or
  `Accept: application/json`), or Markdown (`format=md` or `Accept: text/markdown`). The
  next cursor travels in `X-Transcript-Next-Cursor`.
- `GET .../runs/{run_id}/frames/tail` is a non-canonical Server-Sent Events tail over the
  Native Event Store for dashboards and `--follow`; every event says `canonical: false`.

FT-C4 adds run list and search:

- `GET /v1/applications/{app}/runs?query=&limit=` lists runs through Temporal Visibility
  (bounded grammar, bound to the installation prefix and scope hash) enriched from the
  ledger; a filter outside the grammar is `422 invalid_run_query`.
- `GET .../runs/{run_id}/transcript/search?q=&limit=` ranks the run's projected transcript
  entries (`websearch_to_tsquery` + `ts_rank_cd`) and returns entries with the cursor that
  `run transcript --since` opens.
- `POST .../runs/{run_id}/transcript/refresh` re-projects the run's search documents.

`full=true` reads referenced bodies through the tenant's artifact body reader
(`app.state.mission_control_artifact_body_readers`, same key as the transcript services),
which requires the artifact read grant; without a registered reader it is `501`.

1.4.4 (TRACING-PROPOSAL P4.2): `GET .../runs/{run_id}/transcript?by=&point=&unit=&full=`
returns `mc.transcript_entry.v2` entries placed by unit and point; `by` (`step`, `turn`,
`attempt`, `stage`, `iteration`, `mission`) adds `groups` to the JSON page and renders one
JSONL line per group (entries inline) or a Markdown heading per group; `point` restricts to
one point's entries and its children's, `unit` to one unit key.
`GET .../runs/{run_id}/points/{point_id}/transcript` is the `--by step --point` shortcut.

Authentication and the application/tenant scope are verified exactly as the Mission
Control router does; `workflow_run.read` is required. A malformed cursor is
`409 CURSOR_EXPIRED`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from mission_control.application.frames.search import (
    RunListService,
    RunListUnavailable,
    TranscriptSearchInvalid,
    TranscriptSearchService,
)
from mission_control.application.frames.transcript import (
    FullBodyUnavailable,
    TranscriptDenied,
    TranscriptRunNotFound,
    TranscriptService,
    render_groups_jsonl,
    render_groups_markdown,
)
from mission_control.domain.frames.render import to_jsonl, to_markdown
from mission_control.domain.frames.run_query import RunQueryInvalid
from mission_control.domain.frames.transcript import (
    GROUP_LEVELS,
    CursorExpired,
    TranscriptPage,
    TranscriptQuery,
)
from mission_control.interfaces.http.mission_control import (
    ARTIFACT_BODY_READERS,
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
    principal_request_scope,
)

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["mission-transcript"])

NEXT_CURSOR_HEADER = "X-Transcript-Next-Cursor"
MAX_TAIL_SECONDS = 300.0


def get_transcript_service(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
) -> TranscriptService:
    """The tenant's transcript service, composed with its artifact body reader when one is
    registered (`full=true` stays `501 full_body_unavailable` otherwise)."""

    authorize_application(application_id, request, principal)
    key = (principal.installation_id, application_id, principal.tenant_id)
    registry = getattr(request.app.state, "mission_control_transcript_services", {})
    service = registry.get(key)
    if not isinstance(service, TranscriptService):
        raise HTTPException(status_code=503, detail={"code": "transcript_unavailable"})
    scope = principal_request_scope(principal)
    if service.request_scope != scope:
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    if service.reads_full_bodies:
        return service
    readers = getattr(request.app.state, ARTIFACT_BODY_READERS, {})
    reader = readers.get(key)
    if reader is None:
        return service
    if getattr(reader, "request_scope", None) != scope:
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service.with_artifacts(reader)


Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
Service = Annotated[TranscriptService, Depends(get_transcript_service)]


def _scoped_service(
    application_id: str,
    request: Request,
    principal: MissionPrincipal,
    *,
    registry_name: str,
    kind: type[Any],
    unavailable: str,
) -> Any:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, registry_name, {})
    service = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(service, kind):
        raise HTTPException(status_code=503, detail={"code": unavailable})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service


def get_run_list_service(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
) -> RunListService:
    return _scoped_service(
        application_id,
        request,
        principal,
        registry_name="mission_control_run_list_services",
        kind=RunListService,
        unavailable="run_list_unavailable",
    )


def get_transcript_search_service(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
) -> TranscriptSearchService:
    return _scoped_service(
        application_id,
        request,
        principal,
        registry_name="mission_control_transcript_search_services",
        kind=TranscriptSearchService,
        unavailable="transcript_search_unavailable",
    )


RunList = Annotated[RunListService, Depends(get_run_list_service)]
Search = Annotated[TranscriptSearchService, Depends(get_transcript_search_service)]


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, CursorExpired):
        return HTTPException(
            status_code=409, detail={"code": "CURSOR_EXPIRED", "message": str(exc)}
        )
    if isinstance(exc, TranscriptDenied):
        return HTTPException(status_code=403, detail={"code": "unauthorized"})
    if isinstance(exc, TranscriptRunNotFound):
        return HTTPException(status_code=404, detail={"code": "resource_not_found"})
    if isinstance(exc, FullBodyUnavailable):
        return HTTPException(status_code=501, detail={"code": "full_body_unavailable"})
    return HTTPException(status_code=422, detail={"code": "invalid_transcript_request"})


def _query(
    since: str | None,
    activation: str | None,
    node: str | None,
    kinds: str | None,
    canonical_only: bool,
    subordinate: str | None,
    limit: int,
    *,
    by: str | None = None,
    point: str | None = None,
    unit: str | None = None,
) -> TranscriptQuery:
    if by is not None and by not in GROUP_LEVELS:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_transcript_request", "by": list(GROUP_LEVELS)},
        )
    try:
        return TranscriptQuery(
            since=since or None,
            activation=activation or None,
            node=node or None,
            kinds=frozenset(item.strip() for item in (kinds or "").split(",") if item.strip()),
            canonical_only=canonical_only,
            subordinate=subordinate or None,
            limit=limit,
            by=by,
            point=point or None,
            unit=unit or None,
        )
    except ValueError:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_transcript_request"}
        ) from None


def _format(format_: str | None, accept: str | None) -> str:
    if format_:
        if format_ not in {"jsonl", "json", "md"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_transcript_format"})
        return format_
    accepted = (accept or "").lower()
    if "text/markdown" in accepted:
        return "md"
    if "application/json" in accepted and "ndjson" not in accepted:
        return "json"
    return "jsonl"


def _page_response(
    page: TranscriptPage, kind: str, *, run_id: str, grouped: bool = False
) -> Response:
    """The page as JSONL, JSON or Markdown; `grouped` renders one line (or heading) per
    group with its entries, the JSON page carrying `groups` beside `entries` either way."""

    headers = {
        NEXT_CURSOR_HEADER: page.next_cursor or "",
        "X-Transcript-Has-More": str(page.has_more).lower(),
    }
    if kind == "md":
        return PlainTextResponse(
            render_groups_markdown(page, run_id=run_id)
            if grouped
            else to_markdown(page.entries, run_id=run_id),
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )
    if kind == "json":
        return JSONResponse(page.model_dump(mode="json", exclude_none=True), headers=headers)
    body = render_groups_jsonl(page) if grouped else to_jsonl(page.entries)

    async def stream() -> AsyncIterator[str]:
        for line in body.splitlines(keepends=True):
            yield line

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers=headers)


async def _materialized(
    service: TranscriptService,
    principal: MissionPrincipal,
    run_id: str,
    query: TranscriptQuery,
    *,
    full: bool,
) -> TranscriptPage:
    try:
        return await service.materialize(run_id, actor=principal.actor, query=query, full=full)
    except (CursorExpired, TranscriptDenied, TranscriptRunNotFound, FullBodyUnavailable) as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}/transcript")
async def run_transcript(
    run_id: str,
    principal: Principal,
    service: Service,
    format_: Annotated[str | None, Query(alias="format")] = None,
    since: str | None = None,
    activation: str | None = None,
    node: str | None = None,
    kinds: str | None = None,
    canonical_only: bool = False,
    subordinate: str | None = None,
    limit: Annotated[int, Query(ge=1, le=5_000)] = 500,
    full: bool = False,
    by: str | None = None,
    point: str | None = None,
    unit: str | None = None,
    accept: Annotated[str | None, Header()] = None,
) -> Response:
    query = _query(
        since,
        activation,
        node,
        kinds,
        canonical_only,
        subordinate,
        limit,
        by=by,
        point=point,
        unit=unit,
    )
    kind = _format(format_, accept)
    page = await _materialized(service, principal, run_id, query, full=full)
    return _page_response(page, kind, run_id=run_id, grouped=query.by is not None)


@router.get("/runs/{run_id}/points/{point_id}/transcript")
async def point_transcript(
    run_id: str,
    point_id: str,
    principal: Principal,
    service: Service,
    format_: Annotated[str | None, Query(alias="format")] = None,
    limit: Annotated[int, Query(ge=1, le=5_000)] = 500,
    full: bool = False,
    accept: Annotated[str | None, Header()] = None,
) -> Response:
    """1.4.4 (P4.2): the step group of one point (`--by step --point ID`): its frames, its
    children's and the lifecycle events whose `point_ref` names it."""

    query = _query(None, None, None, None, False, None, limit, by="step", point=point_id)
    kind = _format(format_, accept)
    page = await _materialized(service, principal, run_id, query, full=full)
    return _page_response(page, kind, run_id=run_id, grouped=True)


@router.get("/runs/{run_id}/frames/tail")
async def frames_tail(
    run_id: str,
    principal: Principal,
    service: Service,
    after: str | None = None,
    seconds: Annotated[float, Query(alias="timeout", gt=0, le=MAX_TAIL_SECONDS)] = 30.0,
    poll: Annotated[float, Query(ge=0.05, le=10)] = 1.0,
) -> StreamingResponse:
    """Non-canonical live tail (SSE). Ends after `timeout` seconds with an `end` event."""

    try:
        first = await service.tail_frames(run_id, actor=principal.actor, after=after)
    except (CursorExpired, TranscriptDenied, TranscriptRunNotFound) as exc:
        raise _error(exc) from None

    def sse(event: str, data: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(data, sort_keys=True, ensure_ascii=False)}\n\n"

    async def stream() -> AsyncIterator[str]:
        deadline = time.monotonic() + seconds
        page = first
        cursor = after
        while True:
            for entry in page.entries:
                cursor = entry.cursor
                yield sse(
                    "frame",
                    {**entry.model_dump(mode="json", exclude_none=True), "canonical": False},
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                yield sse("end", {"next_cursor": cursor, "reason": "timeout", "canonical": False})
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(min(poll, remaining))
            page = await service.tail_frames(run_id, actor=principal.actor, after=cursor)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/runs")
async def list_runs(
    principal: Principal,
    service: RunList,
    query: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """FT-C4: runs matching the bounded filter, enriched from the ledger."""

    try:
        page = await service.list(query, actor=principal.actor, limit=limit)
    except RunQueryInvalid as exc:
        raise HTTPException(
            status_code=422, detail={"code": RunQueryInvalid.code, "message": str(exc)}
        ) from None
    except TranscriptDenied:
        raise HTTPException(status_code=403, detail={"code": "unauthorized"}) from None
    except RunListUnavailable:
        raise HTTPException(status_code=503, detail={"code": "run_list_unavailable"}) from None
    return {"application_id": principal.application_id, **page.model_dump(mode="json")}


@router.post("/runs/{run_id}/transcript/refresh")
async def refresh_transcript(run_id: str, principal: Principal, service: Search) -> dict[str, Any]:
    """Re-project the run's searchable transcript documents now; returns the receipt."""

    try:
        receipt = await service.refresh(run_id, actor=principal.actor)
    except (TranscriptDenied, TranscriptRunNotFound) as exc:
        raise _error(exc) from None
    return {"application_id": principal.application_id, **receipt.model_dump(mode="json")}


@router.get("/runs/{run_id}/transcript/search")
async def search_transcript(
    run_id: str,
    principal: Principal,
    service: Search,
    q: Annotated[str, Query(min_length=1, max_length=512)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """FT-C4: ranked transcript entries with the cursor `run transcript --since` opens."""

    try:
        page = await service.search(run_id, q, actor=principal.actor, limit=limit)
    except TranscriptSearchInvalid as exc:
        raise HTTPException(
            status_code=422, detail={"code": TranscriptSearchInvalid.code, "message": str(exc)}
        ) from None
    except (TranscriptDenied, TranscriptRunNotFound) as exc:
        raise _error(exc) from None
    return {
        "application_id": principal.application_id,
        **page.model_dump(mode="json", exclude_none=True),
    }
