"""A scripted provider over the Remote Session Lane base (FIXTURE only, no network).

`ScriptedRemoteLane` answers every provider hook from scripts: each observe call opens the next
stream script (a list of events, or an exception raised at open), the turn record is read from
`records` in order (the last one repeats), and an optional history makes it a provider without
native resume, merged through `replay_then_stream`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from mission_control.adapters.claude.describe import CLAUDE_CLOUD_DESCRIBE
from mission_control.adapters.remote_session.dispatch import DispatchKeyParts
from mission_control.adapters.remote_session.lane import (
    Classified,
    RemoteSession,
    RemoteSessionLane,
)
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import StreamOpened, replay_then_stream
from mission_control.application.execution.harness.dispatch import DispatchLookup, DispatchRecord
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.execution.lanes import (
    CursorExecutionBinding,
    LaneFrame,
    ObserveRequest,
    SessionHandle,
    TurnHandle,
)
from tests.fixtures.cursor_controls import harness_fields
from tests.fixtures.lane_turns import cursor_operation

# A hosted profile no remote lane implements yet stands in for "some provider".
PROFILE: Final = "claude_cloud"
SESSION = "sess-1"
TURN = "turn-1"

StreamScript = Sequence[SseEvent | StreamOpened | Exception] | Exception


def event(
    kind: str, data: Mapping[str, Any] | None = None, event_id: str | None = None
) -> SseEvent:
    return SseEvent(event=kind, data=json.dumps(data or {}), id=event_id)


def opened(retention: int | None = 60, after: str | None = None) -> StreamOpened:
    return StreamOpened(retention_seconds=retention, last_event_id=after)


@dataclass(kw_only=True)
class ScriptedSession(RemoteSession):
    pass


@dataclass
class Calls:
    opened_after: list[str | None] = field(default_factory=list)
    reads: int = 0
    reconciled: list[tuple[str, str]] = field(default_factory=list)


class ScriptedRemoteLane(RemoteSessionLane[ScriptedSession]):
    """`ping` is a keep-alive, `end` closes the stream, `turn.done` is terminal."""

    profile = PROFILE
    terminal_statuses = frozenset({"done", "failed"})

    def __init__(
        self,
        *,
        streams: list[StreamScript] | None = None,
        records: list[dict[str, Any]] | None = None,
        history: list[SseEvent] | None = None,
        poll_limit: int = 3,
    ) -> None:
        super().__init__(
            describe=CLAUDE_CLOUD_DESCRIBE, record_poll_interval_s=0, record_poll_limit=poll_limit
        )
        self.streams = list(streams or [])
        self.records = list(records or [{"status": "running"}])
        self.history = history
        self.calls = Calls()

    def _new_session(self, operation: OperationExecutionRequest) -> ScriptedSession:
        if CursorExecutionBinding.carried_by(operation) is None:
            raise ValueError("the scripted lane runs only a bound operation")
        return ScriptedSession(
            operation=operation, identity=LaneExecutionIdentity.of(operation, PROFILE, 1)
        )

    async def _stream(self, after: str | None) -> AsyncIterator[SseEvent | StreamOpened]:
        self.calls.opened_after.append(after)
        script = self.streams.pop(0)
        if isinstance(script, Exception):
            raise script
        for item in script:
            if isinstance(item, Exception):
                raise item
            yield item

    async def _replay(self) -> AsyncIterator[SseEvent]:
        for item in self.history or ():
            yield item

    def _events(
        self, session: ScriptedSession, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        if self.history is None:
            return self._stream(after)
        return replay_then_stream(self._stream(after), self._replay, lambda item: item.id)

    def _classify(self, event: SseEvent, body: Mapping[str, Any]) -> Classified:
        if event.event == "ping":
            return Classified("skip")
        if event.event == "end":
            return Classified("end")
        return Classified("terminal" if event.event == "turn.done" else "frame", event.event)

    async def _read_turn(self, session_ref: str, turn_ref: str) -> Mapping[str, Any]:
        self.calls.reads += 1
        record = self.records[min(self.calls.reads - 1, len(self.records) - 1)]
        if record.get("status") == "gone":
            raise NativeTurnLost("the scripted turn no longer exists")
        return record

    def _final_key(self, turn_ref: str) -> str:
        return f"scripted:{turn_ref}:final"

    async def _on_terminal(self, session_ref: str, turn_ref: str, body: dict[str, Any]) -> None:
        body["attributed_to"] = f"{session_ref}/{turn_ref}"

    async def _reconcile_create(
        self, record: DispatchRecord, parts: DispatchKeyParts, staged: ScriptedSession | None
    ) -> DispatchLookup:
        self.calls.reconciled.append(("create", parts.harness_execution_id))
        return DispatchLookup(outcome="not_received", detail="scripted create")

    async def _reconcile_send(
        self,
        record: DispatchRecord,
        parts: DispatchKeyParts,
        staged: ScriptedSession | None,
        session: SessionHandle | None,
    ) -> DispatchLookup:
        self.calls.reconciled.append(("send", parts.kind))
        assert staged is not None
        return staged.turns.lookup_latest(record.idempotency_key, "turn-9")

    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts:
        body = frame.body if isinstance(frame.body, Mapping) else {}
        return ClosingFacts(native_status="finished" if body.get("status") == "done" else "error")


def operation() -> OperationExecutionRequest:
    return cursor_operation("cursor_cloud")


def staged_lane(lane: ScriptedRemoteLane, heid: str = "heid-1") -> OperationExecutionRequest:
    op = operation()
    lane.stage(heid, op)
    return op


def observe_request(
    op: OperationExecutionRequest, heid: str = "heid-1", *, after: str | None = None
) -> ObserveRequest:
    return ObserveRequest(
        **harness_fields(op, heid, PROFILE),
        turn=TurnHandle(session=session_handle(heid), turn_no=1, native_turn_ref=TURN),
        after=after,
    )


def session_handle(heid: str = "heid-1", ref: str = SESSION) -> SessionHandle:
    return SessionHandle(
        lane_profile=PROFILE, harness_execution_id=heid, generation=1, native_session_ref=ref
    )


async def observed(lane: ScriptedRemoteLane, request: ObserveRequest) -> list[LaneFrame]:
    return [frame async for frame in lane.observe(request)]
