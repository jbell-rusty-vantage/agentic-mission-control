"""Artifact and frame-body download over HTTP (1.4.4, tracing Stage 1, TR-D3; P4.2).

- `GET /v1/applications/{app}/runs/{run_id}/artifacts/{ref}` answers the verified bytes of a
  `frame-body://sha256:<hex>?bytes=<n>&type=<media>` or `artifact://<scope>/<run>/<id>`
  reference through the tenant's granted body reader (`GrantedArtifactBodyReader`): the
  caller needs `workflow_run.read` and `workflow.result.read`; the digest and byte count are
  verified and the 4 000 000-byte cap applies. `Content-Type` is the media type the run's
  frame row (or the admitted revision) records and `Content-Length` the byte count;
  `X-Content-Digest` carries the sha256 digest. The body is always an attachment
  (`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`).
  `404 artifact_unavailable` when the reference does not resolve, `403` without the grant,
  `413 payload_too_large` over the cap, `501 artifact_download_unavailable` when no payload
  store is composed. The reference travels URL-encoded in the path (`quote(ref, safe="")`,
  as `missionctl run artifact RUN REF --out FILE` sends it).

Tracing Stage 3 (R4-F6): the read is bound to the path's run inside the reader
(`read_bytes(..., run_id=run_id)`). A `frame-body://` digest the run's frames do not
reference, an artifact of another run and an unknown run are all `404`; the reference's own
`bytes=`/`type=` never address or label the bytes (see
`application/frames/artifact_bodies.py`).

OVE-204 slice 5: a `closure-body://sha256:<hex>?bytes=<n>&type=<media>` reference (a promoted
Workspace Closure body) is served the same way, bound to the path's run: the digest must be a
promoted body of one of the run's closures, whose entry row gives the byte count and media
type. A closure body above the 4 000 000-byte cap is recorded but answers `413`.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from mission_control.application.execution.cognition_point_reads import LIST_PERMISSION
from mission_control.application.frames.artifact_bodies import (
    ARTIFACT_READ_PERMISSION,
    ArtifactBodyDenied,
    ArtifactBodyMissing,
    ArtifactBodyTooLarge,
    GrantedArtifactBodyReader,
)
from mission_control.interfaces.http.mission_control import (
    ARTIFACT_BODY_READERS,
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
    principal_request_scope,
    require_permission,
)

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["artifacts"])
DIGEST_HEADER = "X-Content-Digest"


def get_artifact_body_reader(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
) -> GrantedArtifactBodyReader:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, ARTIFACT_BODY_READERS, {})
    reader = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(reader, GrantedArtifactBodyReader):
        raise HTTPException(status_code=501, detail={"code": "artifact_download_unavailable"})
    if reader.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return reader


Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
Reader = Annotated[GrantedArtifactBodyReader, Depends(get_artifact_body_reader)]


@router.get("/runs/{run_id}/artifacts/{ref:path}")
async def download_artifact(
    run_id: str, ref: str, principal: Principal, reader: Reader
) -> Response:
    """The bytes of one `frame-body://`, `closure-body://` or `artifact://` reference."""

    require_permission(principal, LIST_PERMISSION)
    require_permission(principal, ARTIFACT_READ_PERMISSION)
    # The router already percent-decoded the path once; a reference's own encoding (the
    # `type=` value of a `frame-body://` reference) must survive, so no second decode.
    try:
        # Tracing Stage 3 (R4-F6): the reader binds the reference to the path's run.
        content, media_type = await reader.read_bytes(
            principal_request_scope(principal), principal.actor, ref, run_id=run_id
        )
    except ArtifactBodyDenied as error:
        raise HTTPException(
            status_code=403, detail={"code": "forbidden", "reason": str(error)}
        ) from None
    except ArtifactBodyTooLarge as error:
        raise HTTPException(status_code=413, detail={"code": error.code}) from None
    except ArtifactBodyMissing as error:
        raise HTTPException(status_code=404, detail={"code": error.code}) from None
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Length": str(len(content)),
            DIGEST_HEADER: f"sha256:{sha256(content).hexdigest()}",
            "Cache-Control": "no-store",
            # Tracing Stage 3 (R4-F6): evidence bytes are never rendered by the browser.
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["ARTIFACT_BODY_READERS", "DIGEST_HEADER", "router"]
