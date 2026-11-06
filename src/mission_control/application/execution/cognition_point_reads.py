"""Operator reads over the cognition point index (P1 turn 4, K09/K15).

`CognitionPointReadService` lists a run's points under the caller's tenant scope and
answers `state-as-of` for one point through the lane's `read_as_of` (the time-travel
registry is the only router). It is composed per tenant beside the transcript service and
served on HTTP, the CLI and MCP with the same shapes.

1.4.4 (tracing Stage 1, WP-TR-3): `frames_for_point` reads the frames in a point's range
(`frames.from_ordinal..to_ordinal` of the point's harness execution and generation) through
the frame reader composed beside the service, and the granted artifact body reader composed
with it serves replay (`application/frames/replay.py`) and the bodies behind `frame-body://`
references. Both are optional: a service composed without them answers `unavailable`.

OVE-204 slice 5: `closure(run_id, point_id)` and `closures(run_id)` read the Workspace
Closures (`mc.workspace_closure.v1`) through the closure reader composed beside the service,
and `state_as_of` lists a point's closure files (source `closure`, with `body_ref` when the
body was promoted) when the point's `workspace_checkpoint_ref` names a closure. The closure is
read here, under the service's tenant scope, not by the lane (the time-travel lanes are not
tenant-scoped).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from mission_control.application.execution.cognition_points import (
    CognitionPointRepository,
    page_size,
)
from mission_control.application.execution.harness.time_travel import (
    TimeTravelRegistry,
    TimeTravelUnsupported,
)
from mission_control.application.frames.sink import FrameReader
from mission_control.application.frames.transcript import ArtifactBodyReader
from mission_control.domain.execution.cognition_points import (
    CognitionPointFilter,
    CognitionPointPage,
    CognitionPointRecord,
    StateAsOf,
    StateFile,
)
from mission_control.domain.execution.workspace_closure import (
    MalformedClosureRef,
    WorkspaceClosure,
    WorkspaceClosureSummary,
    is_closure_ref,
    parse_closure_ref,
)
from mission_control.domain.frames.contracts import ProviderFrame

LIST_PERMISSION = "workflow_run.read"
STATE_PERMISSION = "workflow_run.read_checkpoint_summary"
FRAMES_PERMISSION = LIST_PERMISSION
MAX_POINT_FRAMES = 10_000


class CognitionPointNotFound(LookupError):
    """No such point in the caller's scope (indistinguishable from another tenant's)."""


class PointFramesUnavailable(LookupError):
    """The point has no frame range (or no harness execution) to read frames for."""

    code = "point_frames_unavailable"


class FrameReaderUnavailable(RuntimeError):
    """The service was composed without a frame reader (`501` on HTTP)."""

    code = "frame_reader_unavailable"


class ClosureUnavailable(RuntimeError):
    """The service was composed without a closure reader (`501` on HTTP)."""

    code = "workspace_closure_unavailable"


class WorkspaceClosureNotFound(LookupError):
    """The point has no Workspace Closure in the caller's scope."""

    code = "workspace_closure_not_found"


class WorkspaceClosureReader(Protocol):
    """Reads Workspace Closures under a tenant scope (`PostgresWorkspaceClosures`)."""

    async def get(self, request_scope: str, closure_id: str) -> WorkspaceClosure | None: ...

    async def for_point(
        self, request_scope: str, run_key: str, point_id: str
    ) -> tuple[WorkspaceClosure, ...]: ...

    async def list_for_run(
        self, request_scope: str, run_key: str
    ) -> tuple[WorkspaceClosureSummary, ...]: ...


class CognitionPointReadService:
    def __init__(
        self,
        repository: CognitionPointRepository,
        *,
        request_scope: str,
        time_travel: TimeTravelRegistry | None = None,
        frames: FrameReader | None = None,
        artifacts: ArtifactBodyReader | None = None,
        closures: WorkspaceClosureReader | None = None,
    ) -> None:
        self._repository = repository
        self._scope = request_scope
        self._time_travel = time_travel or TimeTravelRegistry()
        self._frames = frames
        self._artifacts = artifacts
        self._closures = closures

    @property
    def request_scope(self) -> str:
        return self._scope

    @property
    def time_travel(self) -> TimeTravelRegistry:
        return self._time_travel

    @property
    def frames(self) -> FrameReader | None:
        return self._frames

    @property
    def artifacts(self) -> ArtifactBodyReader | None:
        """The granted body reader composed with the service (replay, promoted bodies)."""

        return self._artifacts

    def with_time_travel(self, time_travel: TimeTravelRegistry) -> CognitionPointReadService:
        """The same service routed through another registry (the API's live one)."""

        return CognitionPointReadService(
            self._repository,
            request_scope=self._scope,
            time_travel=time_travel,
            frames=self._frames,
            artifacts=self._artifacts,
            closures=self._closures,
        )

    async def list_points(
        self,
        run_id: str,
        *,
        selection: CognitionPointFilter | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> CognitionPointPage:
        return await self._repository.list_points(
            self._scope,
            run_id,
            selection=selection or CognitionPointFilter(),
            limit=page_size(limit),
            cursor=cursor,
        )

    async def get_point(self, run_id: str, point_id: str) -> CognitionPointRecord:
        record = await self._repository.get_point(self._scope, point_id)
        if record is None or record.coordinate.run_id != run_id:
            raise CognitionPointNotFound(point_id)
        return record

    async def state_as_of(self, run_id: str, point_id: str) -> StateAsOf:
        """The graph state at the point, read by the lane that wrote it (R3 on Deep Agents)."""

        record = await self.get_point(run_id, point_id)
        if not self._time_travel.supports(record.lane_profile):
            raise TimeTravelUnsupported(record.lane_profile)
        # K3 (2026-11-05): a session lane reads scoped frames and snapshots, so it is
        # bound to this service's request scope; the Deep Agents saver ignores it.
        lane = self._time_travel.lane(record.lane_profile, request_scope=self._scope)
        state = await lane.read_as_of(record)
        return await self._with_closure(state)

    @property
    def closure_reader(self) -> WorkspaceClosureReader | None:
        return self._closures

    async def closure(self, run_id: str, point_id: str) -> WorkspaceClosure:
        """The point's Workspace Closure: the one its ref names, else the newest recorded."""

        if self._closures is None:
            raise ClosureUnavailable("no workspace closure reader is composed")
        record = await self.get_point(run_id, point_id)
        ref = record.workspace_checkpoint_ref
        if ref is not None and is_closure_ref(ref):
            closure = await self._closure_by_ref(ref)
            if closure is not None and closure.run_id == run_id:
                return closure
        found = await self._closures.for_point(self._scope, run_id, point_id)
        if not found:
            raise WorkspaceClosureNotFound(point_id)
        return found[-1]

    async def closures(self, run_id: str) -> tuple[WorkspaceClosureSummary, ...]:
        """Every closure of the run, oldest first; the newest is the mission end's."""

        if self._closures is None:
            raise ClosureUnavailable("no workspace closure reader is composed")
        return await self._closures.list_for_run(self._scope, run_id)

    async def _closure_by_ref(self, ref: str) -> WorkspaceClosure | None:
        assert self._closures is not None
        try:
            closure_id, digest = parse_closure_ref(ref)
        except MalformedClosureRef:
            return None
        closure = await self._closures.get(self._scope, closure_id)
        return closure if closure is not None and closure.closure_digest == digest else None

    async def _with_closure(self, state: StateAsOf) -> StateAsOf:
        """List the point's closure files beside the lane's (a closure file replaces the
        lane's entry for the same path: it carries the raw-byte digest and the body ref)."""

        ref = state.point.workspace_checkpoint_ref
        if self._closures is None or ref is None or not is_closure_ref(ref):
            return state
        closure = await self._closure_by_ref(ref)
        if closure is None:
            graph = state.state.model_copy(
                update={"withheld": (*state.state.withheld, "workspace closure unreadable")}
            )
            return state.model_copy(update={"state": graph, "closure_ref": ref})
        paths = {item.path for item in closure.files}
        files = [item for item in state.state.files if item.path not in paths]
        files.extend(
            StateFile(
                path=item.path,
                size_bytes=item.size_bytes,
                digest=item.digest,
                encoding=item.encoding,
                source="closure",
                body_ref=item.body_ref,
            )
            for item in closure.files
        )
        files.sort(key=lambda item: (item.path, item.source or ""))
        withheld = list(state.state.withheld)
        if not closure.complete:
            withheld.append(f"workspace closure incomplete: {', '.join(closure.limits.applied)}")
        graph = state.state.model_copy(update={"files": tuple(files), "withheld": tuple(withheld)})
        return state.model_copy(update={"state": graph, "closure_ref": ref})

    async def frames_for_point(
        self,
        run_id: str,
        point_id: str,
        *,
        frames: FrameReader | None = None,
    ) -> tuple[ProviderFrame, ...]:
        """The frames recorded while the point's step ran, in arrival order (1.4.4, P4.2).

        The range is `frames.from_ordinal..to_ordinal` of the point's harness execution and
        execution generation; a point without a range (or without an execution) raises
        `PointFramesUnavailable`.
        """

        reader = frames or self._frames
        if reader is None:
            raise FrameReaderUnavailable("no frame reader is composed with the point service")
        record = await self.get_point(run_id, point_id)
        window = record.frames
        execution = record.coordinate.harness_execution_id
        if window is None or execution is None:
            raise PointFramesUnavailable(point_id)
        try:
            harness = UUID(execution)
        except ValueError:
            raise PointFramesUnavailable(point_id) from None
        span = window.to_ordinal - window.from_ordinal + 1
        rows = await reader.frames_for_execution(
            self._scope,
            harness,
            record.coordinate.execution_generation,
            after_ordinal=window.from_ordinal - 1,
            limit=min(span, MAX_POINT_FRAMES),
        )
        return tuple(frame for frame in rows if frame.arrival_ordinal <= window.to_ordinal)

    async def frames_for_run(
        self, run_uuid: UUID, *, frames: FrameReader | None = None
    ) -> tuple[ProviderFrame, ...]:
        """Every frame of the run under the service's scope (the replay's id index)."""

        reader = frames or self._frames
        if reader is None:
            raise FrameReaderUnavailable("no frame reader is composed with the point service")
        return await reader.frames_for_run(self._scope, run_uuid, limit=MAX_POINT_FRAMES)


__all__ = [
    "FRAMES_PERMISSION",
    "LIST_PERMISSION",
    "MAX_POINT_FRAMES",
    "STATE_PERMISSION",
    "ClosureUnavailable",
    "CognitionPointNotFound",
    "CognitionPointReadService",
    "FrameReaderUnavailable",
    "PointFramesUnavailable",
    "WorkspaceClosureNotFound",
    "WorkspaceClosureReader",
]
