"""In-memory Workspace Closure store for unit tests (OVE-204 slice 5).

Implements the adapter's `WorkspaceClosurePort`, the read service's `WorkspaceClosureReader`
and the body reader's `ClosureBodyIndex` with the PostgreSQL adapter's idempotency rule: the
first closure recorded for an id stands.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from mission_control.application.frames.artifact_bodies import FrameBodyRecord
from mission_control.domain.execution.workspace_closure import (
    WorkspaceClosure,
    WorkspaceClosureSummary,
)


class InMemoryWorkspaceClosures:
    def __init__(self) -> None:
        self.closures: dict[str, tuple[str, WorkspaceClosure, datetime | None]] = {}
        self.bodies: dict[str, bytes] = {}

    async def put(
        self,
        closure: WorkspaceClosure,
        bodies: Mapping[str, bytes],
        *,
        request_scope: str,
        retain_until: datetime | None,
    ) -> None:
        for item in closure.files:
            if item.body_state == "promoted":
                self.bodies[item.digest] = bodies[item.digest]
        self.closures.setdefault(closure.closure_id, (request_scope, closure, retain_until))

    async def get(self, request_scope: str, closure_id: str) -> WorkspaceClosure | None:
        found = self.closures.get(closure_id)
        return found[1] if found is not None and found[0] == request_scope else None

    async def for_point(
        self, request_scope: str, run_key: str, point_id: str
    ) -> tuple[WorkspaceClosure, ...]:
        return tuple(
            closure
            for scope, closure, _retain in self._ordered()
            if scope == request_scope and closure.run_id == run_key and closure.point_id == point_id
        )

    async def list_for_run(
        self, request_scope: str, run_key: str
    ) -> tuple[WorkspaceClosureSummary, ...]:
        return tuple(
            WorkspaceClosureSummary.of(closure, retain_until=retain)
            for scope, closure, retain in self._ordered()
            if scope == request_scope and closure.run_id == run_key
        )

    async def run_closure_body(
        self, request_scope: str, run_key: str, digest: str
    ) -> FrameBodyRecord | None:
        for scope, closure, _retain in self._ordered():
            if scope != request_scope or closure.run_id != run_key:
                continue
            for item in closure.files:
                if item.digest == digest and item.body_state == "promoted":
                    return FrameBodyRecord(size_bytes=item.size_bytes, media_type=item.media_type)
        return None

    def only(self) -> WorkspaceClosure:
        (entry,) = self.closures.values()
        return entry[1]

    def _ordered(self) -> list[tuple[str, WorkspaceClosure, datetime | None]]:
        return sorted(self.closures.values(), key=lambda item: item[1].recorded_at)
