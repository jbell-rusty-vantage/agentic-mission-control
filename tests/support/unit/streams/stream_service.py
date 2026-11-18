"""Builders, constants and fakes that other test files import.

Moved from tests/unit/streams/test_stream_service.py.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from mission_control.application.streams.service import MissionStreamService
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.subscriptions.streams import (
    StreamCursor,
    StreamFilters,
    StreamSubscription,
    StreamTarget,
)
from tests.support.provider_frames import FIXTURE_HARNESS
from tests.unit.streams.fakes import RUN_KEY, FakeStreamSource

READER = ActorContext(actor_id="viewer", permissions=frozenset({"workflow_run.read"}))


def service(source: FakeStreamSource | None = None) -> tuple[MissionStreamService, Any]:
    source = source or FakeStreamSource()
    return MissionStreamService(source, request_scope=source.request_scope), source


def subscription(
    svc: MissionStreamService,
    *,
    kind: str = "run",
    target_id: str = RUN_KEY,
    streams: tuple[str, ...] = ("mission_events",),
    cursors: tuple[StreamCursor, ...] = (),
    filters: StreamFilters | None = None,
    **extra: Any,
) -> StreamSubscription:
    return StreamSubscription(
        subscription_id=f"sub-{uuid4()}",
        request_id="req-1",
        scope=svc.scope,
        target=StreamTarget(kind=kind, id=target_id),  # type: ignore[arg-type]
        streams=streams,  # type: ignore[arg-type]
        cursors=cursors,
        filters=filters or StreamFilters(),
        **extra,
    )


def mission_at(seq: int) -> StreamCursor:
    return StreamCursor(stream="mission_events", position=str(seq))


def frames_at(ordinal: int, generation: int | None = 1, execution: Any = None) -> StreamCursor:
    return StreamCursor(
        stream="provider_frames",
        position=f"{execution or FIXTURE_HARNESS}:{ordinal}",
        generation=generation,
    )


def execution_subscription(svc: MissionStreamService, **kwargs: Any) -> StreamSubscription:
    return subscription(
        svc,
        kind="execution",
        target_id=str(FIXTURE_HARNESS),
        streams=("mission_events", "provider_frames"),
        **kwargs,
    )
