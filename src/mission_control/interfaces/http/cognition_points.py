"""Cognition points over HTTP (P1 turn 4, K09/K15; `mc.cognition_point.v1`).

- `GET /v1/applications/{app}/runs/{run_id}/points` lists the run's points, newest last,
  filtered by `unit_key`, `generation`, `node` (stage id or goal role), `iteration` (goal
  iteration or workflow cycle), `cycle` (stage cycle), `session_generation`, `kind`, `role`
  and `seedable`; paged with `limit` and `cursor` (`workflow_run.read`).
- `GET .../runs/{run_id}/points/{point_id}` returns one point.
- `GET .../runs/{run_id}/points/{point_id}/state-as-of` returns `mc.state_as_of.v1`: the
  graph state at the point as the lane reads it, redacted (`workflow_run.read_checkpoint_summary`).
- `POST .../runs/{run_id}/points:reconcile` (1.4.4, TR-D6; `workflow_run.reconcile_unit`,
  optional body `{"unit_key": ...}`) re-derives the points a settlement left short and
  answers `mc.points_reconciliation.v1`.
- `GET .../runs/{run_id}/points/{point_id}/frames` (1.4.4, P4.2; `workflow_run.read`)
  returns `{"frames": [mc.provider_frame.v1, ...]}`: the frames in the point's range, in
  arrival order; `404 point_frames_unavailable` when the point has no range.
- `GET .../runs/{run_id}/points/{point_id}/replay?call_index=&include_batch=` (1.4.4, P4.3;
  `workflow_run.read` and `workflow.result.read`) answers `mc.replay_report.v1`: the model
  input of the step reconstructed from the Transcript and compared with the recorded
  digests (`application/frames/replay.py`). Nothing is sent to a model.

- `GET .../runs/{run_id}/points/{point_id}/closure` (OVE-204 slice 5; `workflow_run.read`
  and `workflow_run.read_checkpoint_summary`) answers the point's Workspace Closure
  (`mc.workspace_closure.v1`): every file the agent could see at the attempt's settled
  boundary with its raw-byte digest, slot, destination and body state; promoted bodies carry a
  `closure-body://` reference for the run's artifact download route. `404
  workspace_closure_not_found` when none was recorded, `501 workspace_closure_unavailable`
  without a composed reader.
- `GET .../runs/{run_id}/closures` (`workflow_run.read`) answers
  `{"closures": [summary, ...]}`, oldest first; the newest is the mission end's closure.

Authentication and the application/tenant scope are verified exactly as the Mission Control
router does. The time-travel registry (`app.state.time_travel_registry`) is composed by the
runtime control bootstrap; without it `state-as-of` answers `501 time_travel_unavailable`.
The reconciler (`app.state.mission_control_point_reconcilers`) is composed by the API
bootstrap beside the saver; without it `points:reconcile` answers `503`. The frame reader
and the granted body reader are composed into the point service by the API bootstrap; the
replay service (`app.state.mission_control_replay_services`) beside it. Without a frame
reader the frame routes answer `501 frame_reader_unavailable`; without a body reader
`replay` answers `501 replay_unavailable`.
"""

from __future__ import annotations

import contextlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.execution.cognition_point_reads import (
    FRAMES_PERMISSION,
    LIST_PERMISSION,
    STATE_PERMISSION,
    ClosureUnavailable,
    CognitionPointNotFound,
    CognitionPointReadService,
    FrameReaderUnavailable,
    PointFramesUnavailable,
)
from mission_control.application.execution.harness.time_travel import (
    TimeTravelRegistry,
    TimeTravelUnsupported,
)
from mission_control.application.execution.operations.point_reconciliation import (
    RECONCILE_PERMISSION,
    PointReconciler,
    PointReconciliationDenied,
)
from mission_control.application.frames.artifact_bodies import ArtifactBodyDenied
from mission_control.application.frames.replay import (
    REPLAY_PERMISSION,
    ModelRequestNotFound,
    ReplayDenied,
    ReplayService,
    ReplayUnavailable,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointFilter,
    CognitionPointKind,
    PointRole,
)
from mission_control.domain.frames.transcript import TranscriptQuery
from mission_control.domain.graph_runtime.identities import UNIT_KEY_PATTERN
from mission_control.domain.policies.errors import RunControlNotFound
from mission_control.interfaces.http.mission_control import (
    ARTIFACT_BODY_READERS,
    MissionPrincipal,
    authorize_application,
    forbidden,
    get_mission_principal,
    principal_request_scope,
    require_permission,
)
from mission_control.interfaces.http.transcript import get_transcript_service

# 1.4.4 (P6.1): the reasons that make a point read a typed 503 instead of a 501.
SAVER_OUTCOMES = frozenset({"saver_unreachable", "saver_not_served"})

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["cognition-points"])
SERVICES = "mission_control_cognition_point_services"
TIME_TRAVEL = "time_travel_registry"
RECONCILERS = "mission_control_point_reconcilers"
REPLAY_SERVICES = "mission_control_replay_services"


class ReconcilePointsRequest(BaseModel):
    """Optional body of `points:reconcile`: narrow the pass to one unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_key: str | None = Field(default=None, pattern=UNIT_KEY_PATTERN)


def get_point_reconciler(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
) -> PointReconciler:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, RECONCILERS, {})
    reconciler = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(reconciler, PointReconciler):
        raise HTTPException(status_code=503, detail={"code": "points_reconciliation_unavailable"})
    return reconciler


def get_point_service(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
) -> CognitionPointReadService:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, SERVICES, {})
    service = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(service, CognitionPointReadService):
        raise HTTPException(status_code=503, detail={"code": "cognition_points_unavailable"})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    time_travel = getattr(request.app.state, TIME_TRAVEL, None)
    if isinstance(time_travel, TimeTravelRegistry) and service.time_travel is not time_travel:
        return service.with_time_travel(time_travel)
    return service


def get_replay_service(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
    service: Annotated[CognitionPointReadService, Depends(get_point_service)],
) -> ReplayService:
    """The tenant's replay service: the one the bootstrap composed, else one over the point
    service and the tenant's granted body reader (the transcript's `full=true` reader)."""

    key = (principal.installation_id, application_id, principal.tenant_id)
    registry = getattr(request.app.state, REPLAY_SERVICES, {})
    replay = registry.get(key)
    if isinstance(replay, ReplayService):
        if replay.request_scope != service.request_scope:
            raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
        return replay
    reader = getattr(request.app.state, ARTIFACT_BODY_READERS, {}).get(key)
    if reader is not None and getattr(reader, "request_scope", None) != service.request_scope:
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return ReplayService(service, artifacts=reader)


Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
Service = Annotated[CognitionPointReadService, Depends(get_point_service)]
Replay = Annotated[ReplayService, Depends(get_replay_service)]


@router.get("/runs/{run_id}/points")
async def list_points(
    run_id: str,
    principal: Principal,
    service: Service,
    unit_key: str | None = None,
    generation: Annotated[int | None, Query(ge=1)] = None,
    node: str | None = None,
    iteration: Annotated[int | None, Query(ge=0)] = None,
    cycle: Annotated[int | None, Query(ge=0)] = None,
    session_generation: Annotated[int | None, Query(ge=1)] = None,
    kind: CognitionPointKind | None = None,
    role: PointRole | None = None,
    seedable: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    require_permission(principal, LIST_PERMISSION)
    try:
        selection = CognitionPointFilter(
            unit_key=unit_key,
            execution_generation=generation,
            node_key=node,
            iteration=iteration,
            cycle=cycle,
            session_generation=session_generation,
            kind=kind,
            role=role,
            seedable_only=seedable,
        )
        page = await service.list_points(run_id, selection=selection, limit=limit, cursor=cursor)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_points_query"}) from error
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from None
    return {"application_id": principal.application_id, **page.model_dump(mode="json")}


@router.get("/runs/{run_id}/points/{point_id}")
async def get_point(
    run_id: str, point_id: str, principal: Principal, service: Service
) -> dict[str, Any]:
    require_permission(principal, LIST_PERMISSION)
    try:
        record = await service.get_point(run_id, point_id)
    except LookupError:  # `CognitionPointNotFound` is one
        raise HTTPException(status_code=404, detail={"code": "point_not_found"}) from None
    return {"application_id": principal.application_id, **record.model_dump(mode="json")}


@router.get("/runs/{run_id}/points/{point_id}/state-as-of")
async def state_as_of(
    run_id: str, point_id: str, principal: Principal, service: Service
) -> dict[str, Any]:
    require_permission(principal, LIST_PERMISSION)
    require_permission(principal, STATE_PERMISSION)
    try:
        state = await service.state_as_of(run_id, point_id)
    except CognitionPointNotFound:
        raise HTTPException(status_code=404, detail={"code": "point_not_found"}) from None
    except TimeTravelUnsupported as error:
        if error.reason in SAVER_OUTCOMES:
            # 1.4.4 (P6.1): the saver did not answer (or serves another location); the
            # Transcript and the points still do, and the point's restore level says what a
            # reconstruction could still give.
            restore_level: str | None = None
            with contextlib.suppress(LookupError):
                restore_level = (await service.get_point(run_id, point_id)).restore_level
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "state_unavailable",
                    "reason": error.reason,
                    "saver": error.saver,
                    "restore_level": restore_level,
                    "withheld": {
                        "state": error.reason,
                        "transcript": "answers",
                        "points": "answer",
                    },
                },
            ) from None
        if error.reason == "checkpoint_missing":
            # Tracing Stage 3 (R2-19): the point's saver state is gone (pruned or never
            # written); the point exists, its state does not. Not an unimplemented feature.
            raise HTTPException(
                status_code=404,
                detail={"code": "point_state_missing", "reason": error.reason},
            ) from None
        raise HTTPException(
            status_code=501,
            detail={"code": "time_travel_unavailable", "reason": error.reason},
        ) from None
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from None
    return {"application_id": principal.application_id, **state.model_dump(mode="json")}


@router.get("/runs/{run_id}/points/{point_id}/closure")
async def point_closure(
    run_id: str, point_id: str, principal: Principal, service: Service
) -> dict[str, Any]:
    """OVE-204 slice 5: the point's Workspace Closure (`mc.workspace_closure.v1`)."""

    require_permission(principal, LIST_PERMISSION)
    require_permission(principal, STATE_PERMISSION)
    try:
        closure = await service.closure(run_id, point_id)
    except ClosureUnavailable:
        raise HTTPException(
            status_code=501, detail={"code": "workspace_closure_unavailable"}
        ) from None
    except CognitionPointNotFound:
        raise HTTPException(status_code=404, detail={"code": "point_not_found"}) from None
    except LookupError:  # `WorkspaceClosureNotFound` is one
        raise HTTPException(
            status_code=404, detail={"code": "workspace_closure_not_found"}
        ) from None
    return {"application_id": principal.application_id, **closure.model_dump(mode="json")}


@router.get("/runs/{run_id}/closures")
async def run_closures(run_id: str, principal: Principal, service: Service) -> dict[str, Any]:
    """OVE-204 slice 5: every Workspace Closure of the run, oldest first."""

    require_permission(principal, LIST_PERMISSION)
    try:
        closures = await service.closures(run_id)
    except ClosureUnavailable:
        raise HTTPException(
            status_code=501, detail={"code": "workspace_closure_unavailable"}
        ) from None
    return {
        "application_id": principal.application_id,
        "run_id": run_id,
        "closures": [item.model_dump(mode="json") for item in closures],
    }


@router.get("/runs/{run_id}/points/{point_id}/frames")
async def point_frames(
    application_id: str,
    run_id: str,
    point_id: str,
    request: Request,
    principal: Principal,
    service: Service,
) -> dict[str, Any]:
    """The frames in the point's range (1.4.4, P4.2): `frames` as `mc.provider_frame.v1`
    rows and `entries` as the Transcript's `mc.transcript_entry.v2` entries of the same
    frames (the proposal's "same entry contract"), when the tenant's transcript service is
    composed."""

    require_permission(principal, FRAMES_PERMISSION)
    try:
        frames = await service.frames_for_point(run_id, point_id)
    except CognitionPointNotFound:
        raise HTTPException(status_code=404, detail={"code": "point_not_found"}) from None
    except PointFramesUnavailable as error:
        raise HTTPException(status_code=404, detail={"code": error.code}) from None
    except FrameReaderUnavailable as error:
        raise HTTPException(status_code=501, detail={"code": error.code}) from None
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from None
    entries: list[dict[str, Any]] = []
    try:
        transcripts = get_transcript_service(application_id, request, principal)
    except HTTPException:
        transcripts = None
    if transcripts is not None:
        frame_ids = {str(frame.frame_id) for frame in frames}
        page = await transcripts.materialize(
            run_id, actor=principal.actor, query=TranscriptQuery(point=point_id, limit=5_000)
        )
        entries = [
            entry.model_dump(mode="json", exclude_none=True)
            for entry in page.entries
            if entry.source == "provider_frame" and entry.refs.frame_id in frame_ids
        ]
    return {
        "application_id": principal.application_id,
        "run_id": run_id,
        "point_id": point_id,
        "frames": [frame.model_dump(mode="json", exclude_none=True) for frame in frames],
        "entries": entries,
    }


@router.get("/runs/{run_id}/points/{point_id}/replay")
async def replay_point(
    run_id: str,
    point_id: str,
    principal: Principal,
    replay: Replay,
    call_index: Annotated[int | None, Query(ge=0)] = None,
    include_batch: bool = False,
) -> dict[str, Any]:
    """Dry-run replay: `mc.replay_report.v1` for one model call of the point (1.4.4, P4.3)."""

    require_permission(principal, LIST_PERMISSION)
    require_permission(principal, REPLAY_PERMISSION)
    try:
        report = await replay.dry_run(
            principal_request_scope(principal),
            principal.actor,
            run_id,
            point_id,
            call_index=call_index,
            include_batch=include_batch,
        )
    except (ReplayDenied, ArtifactBodyDenied) as error:
        raise HTTPException(
            status_code=403, detail={"code": "forbidden", "reason": str(error)}
        ) from None
    except CognitionPointNotFound:
        raise HTTPException(status_code=404, detail={"code": "point_not_found"}) from None
    except (PointFramesUnavailable, ModelRequestNotFound) as error:
        raise HTTPException(status_code=404, detail={"code": error.code}) from None
    except (FrameReaderUnavailable, ReplayUnavailable) as error:
        raise HTTPException(
            status_code=501, detail={"code": error.code, "reason": str(error)}
        ) from None
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from None
    return {"application_id": principal.application_id, **report.model_dump(mode="json")}


@router.post("/runs/{run_id}/points:reconcile")
async def reconcile_points(
    run_id: str,
    principal: Principal,
    reconciler: Annotated[PointReconciler, Depends(get_point_reconciler)],
    body: ReconcilePointsRequest | None = None,
) -> dict[str, Any]:
    """Re-derive the run's missing points and frame ranges (`mc.points_reconciliation.v1`)."""

    require_permission(principal, RECONCILE_PERMISSION)
    try:
        outcome = await reconciler.reconcile(
            principal_request_scope(principal),
            run_id,
            unit_key=body.unit_key if body is not None else None,
            actor=principal.actor,
        )
    except PointReconciliationDenied:
        raise forbidden(RECONCILE_PERMISSION) from None
    except (RunControlNotFound, LookupError):
        raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from None
    return {"application_id": principal.application_id, **outcome.model_dump(mode="json")}


__all__ = [
    "ARTIFACT_BODY_READERS",
    "RECONCILERS",
    "REPLAY_SERVICES",
    "SERVICES",
    "TIME_TRAVEL",
    "ReconcilePointsRequest",
    "router",
]
