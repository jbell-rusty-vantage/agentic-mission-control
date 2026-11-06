"""Cognition points on the coordinator and operator MCP servers (P1 turn 4, K09/K15).

- tool `mission_run_points(run_id, node?, iteration?, cycle?, role?, kind?, session_generation?,
  unit_key?, seedable?, limit?, cursor?)`: one page of `mc.cognition_point.v1` rows.
- tool `mission_run_state_as_of(run_id, point_id)`: `mc.state_as_of.v1` for one point.
- tool `mission_run_points_reconcile(run_id, unit_key?)` (1.4.4, TR-D6): re-derives the
  points a settlement left short; `mc.points_reconciliation.v1`
  (`workflow_run.reconcile_unit`; the API process composes the reconciler beside the saver).
- tool `mission_run_point_frames(run_id, point_id)` (1.4.4, P4.2): the frames in the
  point's range as `mc.provider_frame.v1` rows (`workflow_run.read`).
- tool `mission_run_replay(run_id, point_id, call_index?, include_batch?, dry_run=True)`
  (1.4.4, P4.3): `mc.replay_report.v1`, the step's model input reconstructed from the
  Transcript and compared with the recorded digests (`workflow_run.read` and
  `workflow.result.read`). `dry_run=False` (a paid replay) is not available and answers
  `paid_replay_not_available`.

All return exactly what the HTTP surface returns for the same principal; the reads are
annotated read-only. The principal's request scope selects the tenant's service; a principal
from another scope is refused, and `state_as_of` needs `workflow_run.read_checkpoint_summary`.
The frame reader and the body reader reach the tools through the point read service they
were composed with (`bootstrap/api.py`); a `replays` mapping may override the replay service.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol

from fastmcp import Context, FastMCP

from mission_control.application.execution.cognition_point_reads import (
    FRAMES_PERMISSION,
    LIST_PERMISSION,
    STATE_PERMISSION,
    CognitionPointNotFound,
    CognitionPointReadService,
    FrameReaderUnavailable,
    PointFramesUnavailable,
)
from mission_control.application.execution.harness.time_travel import TimeTravelUnsupported
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
from mission_control.domain.coordinator.errors import CoordinatorDomainError, CoordinatorErrorCode
from mission_control.domain.execution.cognition_points import CognitionPointFilter
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.policies.errors import RunControlNotFound

POINTS_TOOL = "mission_run_points"
STATE_AS_OF_TOOL = "mission_run_state_as_of"
# 1.4.4 (P6.1): the saver did not answer, or serves another location (the HTTP 503 set).
SAVER_OUTCOMES = frozenset({"saver_unreachable", "saver_not_served"})
RECONCILE_TOOL = "mission_run_points_reconcile"
POINT_FRAMES_TOOL = "mission_run_point_frames"
REPLAY_TOOL = "mission_run_replay"


class PointsPrincipal(Protocol):
    @property
    def permissions(self) -> frozenset[str]: ...

    @property
    def request_scope(self) -> str: ...


class PrincipalResolver(Protocol):
    async def resolve(self, context: Context) -> Any: ...


def _actor(principal: PointsPrincipal, fallback: str) -> ActorContext:
    return ActorContext(
        actor_id=str(getattr(principal, "actor_id", None) or fallback),
        permissions=frozenset(principal.permissions),
    )


class ScopedCognitionPoints:
    """Selects the point read service (and the reconciler, when the process composed one)
    of the principal's verified tenant scope."""

    def __init__(
        self,
        services: Mapping[str, CognitionPointReadService],
        *,
        reconcilers: Mapping[str, PointReconciler] | None = None,
        replays: Mapping[str, ReplayService] | None = None,
    ) -> None:
        self._services = dict(services)
        self._reconcilers = dict(reconcilers or {})
        self._replays = dict(replays or {})

    def _service(self, principal: PointsPrincipal, permission: str) -> CognitionPointReadService:
        service = self._services.get(principal.request_scope)
        if service is None or service.request_scope != principal.request_scope:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message="service unavailable for scope"
            )
        if permission not in principal.permissions:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message=f"{permission} permission required"
            )
        return service

    async def reconcile(
        self, principal: PointsPrincipal, *, run_id: str, unit_key: str | None
    ) -> dict[str, Any]:
        self._service(principal, RECONCILE_PERMISSION)
        reconciler = self._reconcilers.get(principal.request_scope)
        if reconciler is None:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.DEPENDENCY_UNAVAILABLE,
                message="points reconciliation unavailable: this process composed no saver",
            )
        actor = _actor(principal, "mcp:points-reconcile")
        try:
            outcome = await reconciler.reconcile(
                principal.request_scope, run_id, unit_key=unit_key, actor=actor
            )
        except PointReconciliationDenied as error:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message=str(error)
            ) from None
        except (RunControlNotFound, LookupError):
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.NOT_FOUND, message="run not found"
            ) from None
        return outcome.model_dump(mode="json")

    async def points(
        self,
        principal: PointsPrincipal,
        *,
        run_id: str,
        selection: CognitionPointFilter,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        service = self._service(principal, LIST_PERMISSION)
        page = await service.list_points(run_id, selection=selection, limit=limit, cursor=cursor)
        return page.model_dump(mode="json")

    async def state_as_of(
        self, principal: PointsPrincipal, *, run_id: str, point_id: str
    ) -> dict[str, Any]:
        service = self._service(principal, STATE_PERMISSION)
        try:
            state = await service.state_as_of(run_id, point_id)
        except CognitionPointNotFound:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.NOT_FOUND, message="cognition point not found"
            ) from None
        except TimeTravelUnsupported as error:
            # Tracing Stage 3 (R2-19): the HTTP surface's facts travel with the error: the
            # reason, the saver it is about and, for a saver that did not answer (retryable),
            # the point's restore level (what a reconstruction could still give).
            details = {"reason": error.reason}
            if error.saver is not None:
                details["saver"] = error.saver
            saver_outcome = error.reason in SAVER_OUTCOMES
            if saver_outcome:
                try:
                    restore_level = (await service.get_point(run_id, point_id)).restore_level
                except (CognitionPointNotFound, LookupError):
                    restore_level = None
                if restore_level is not None:
                    details["restore_level"] = restore_level
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.DEPENDENCY_UNAVAILABLE,
                message=f"time travel {error.reason}",
                retryable=saver_outcome,
                details=details,
            ) from None
        return state.model_dump(mode="json")

    async def point_frames(
        self, principal: PointsPrincipal, *, run_id: str, point_id: str
    ) -> dict[str, Any]:
        """The frames in the point's range (`mc.provider_frame.v1` rows; 1.4.4, P4.2)."""

        service = self._service(principal, FRAMES_PERMISSION)
        try:
            frames = await service.frames_for_point(run_id, point_id)
        except CognitionPointNotFound:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.NOT_FOUND, message="cognition point not found"
            ) from None
        except PointFramesUnavailable:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.NOT_FOUND, message="the point has no frame range"
            ) from None
        except FrameReaderUnavailable as error:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.DEPENDENCY_UNAVAILABLE, message=str(error)
            ) from None
        return {
            "run_id": run_id,
            "point_id": point_id,
            "frames": [frame.model_dump(mode="json", exclude_none=True) for frame in frames],
        }

    async def replay(
        self,
        principal: PointsPrincipal,
        *,
        run_id: str,
        point_id: str,
        call_index: int | None,
        include_batch: bool,
        dry_run: bool,
    ) -> dict[str, Any]:
        """Dry-run replay (`mc.replay_report.v1`; 1.4.4, P4.3). A paid replay is refused."""

        if not dry_run:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.INVALID_ARGUMENT, message="paid_replay_not_available"
            )
        service = self._service(principal, LIST_PERMISSION)
        self._service(principal, REPLAY_PERMISSION)
        replay = self._replays.get(principal.request_scope) or ReplayService(service)
        try:
            report = await replay.dry_run(
                principal.request_scope,
                _actor(principal, "mcp:replay"),
                run_id,
                point_id,
                call_index=call_index,
                include_batch=include_batch,
            )
        except (ReplayDenied, ArtifactBodyDenied) as error:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message=str(error)
            ) from None
        except CognitionPointNotFound:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.NOT_FOUND, message="cognition point not found"
            ) from None
        except (PointFramesUnavailable, ModelRequestNotFound) as error:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.NOT_FOUND, message=error.code
            ) from None
        except (FrameReaderUnavailable, ReplayUnavailable) as error:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.DEPENDENCY_UNAVAILABLE, message=str(error)
            ) from None
        return report.model_dump(mode="json")


def register_cognition_point_tools(
    server: FastMCP,
    points: ScopedCognitionPoints,
    principals: PrincipalResolver,
    *,
    call: Any,
) -> None:
    """Register the point tools; `call` wraps results in the MCP envelope."""

    @server.tool(name=POINTS_TOOL, annotations={"readOnlyHint": True})
    async def mission_run_points(
        run_id: str,
        context: Context,
        node: str | None = None,
        iteration: int | None = None,
        cycle: int | None = None,
        role: str | None = None,
        kind: Literal["checkpoint", "session_cursor", "thread_item", "workspace_snapshot"]
        | None = None,
        session_generation: int | None = None,
        unit_key: str | None = None,
        seedable: bool = False,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, object]:
        async def invoke(principal: Any) -> object:
            selection = CognitionPointFilter(
                node_key=node,
                iteration=iteration,
                cycle=cycle,
                role=role,
                kind=kind,
                session_generation=session_generation,
                unit_key=unit_key,
                seedable_only=seedable,
            )
            return await points.points(
                principal, run_id=run_id, selection=selection, limit=limit, cursor=cursor
            )

        return await call(context, principals, invoke)

    @server.tool(name=STATE_AS_OF_TOOL, annotations={"readOnlyHint": True})
    async def mission_run_state_as_of(
        run_id: str, point_id: str, context: Context
    ) -> dict[str, object]:
        async def invoke(principal: Any) -> object:
            return await points.state_as_of(principal, run_id=run_id, point_id=point_id)

        return await call(context, principals, invoke)

    @server.tool(name=RECONCILE_TOOL, annotations={"readOnlyHint": False, "idempotentHint": True})
    async def mission_run_points_reconcile(
        run_id: str, context: Context, unit_key: str | None = None
    ) -> dict[str, object]:
        async def invoke(principal: Any) -> object:
            return await points.reconcile(principal, run_id=run_id, unit_key=unit_key)

        return await call(context, principals, invoke)

    @server.tool(name=POINT_FRAMES_TOOL, annotations={"readOnlyHint": True})
    async def mission_run_point_frames(
        run_id: str, point_id: str, context: Context
    ) -> dict[str, object]:
        async def invoke(principal: Any) -> object:
            return await points.point_frames(principal, run_id=run_id, point_id=point_id)

        return await call(context, principals, invoke)

    @server.tool(name=REPLAY_TOOL, annotations={"readOnlyHint": True})
    async def mission_run_replay(
        run_id: str,
        point_id: str,
        context: Context,
        call_index: int | None = None,
        include_batch: bool = False,
        dry_run: bool = True,
    ) -> dict[str, object]:
        async def invoke(principal: Any) -> object:
            return await points.replay(
                principal,
                run_id=run_id,
                point_id=point_id,
                call_index=call_index,
                include_batch=include_batch,
                dry_run=dry_run,
            )

        return await call(context, principals, invoke)


__all__ = [
    "POINTS_TOOL",
    "POINT_FRAMES_TOOL",
    "RECONCILE_TOOL",
    "REPLAY_TOOL",
    "STATE_AS_OF_TOOL",
    "ScopedCognitionPoints",
    "register_cognition_point_tools",
]
