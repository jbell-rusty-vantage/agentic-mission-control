"""The Remote Session Lane base (ADR-0052; SPEC-06 section 3).

A Remote Session Lane drives an agent loop that a provider runs behind a session API: Cursor
Cloud Agents (`cursor_cloud`), Anthropic Managed Agents (`claude_managed`) and the OpenAI Agents
API (`codex_agents`). The session lives at the provider; the lane holds only process-local
state (`RemoteSession`) that a reattach can rebuild, and `LaneTurnService` keeps everything
durable (dispatch journal, Stop Fence, session ownership, persisted frames as the resume truth).

`RemoteSessionLane` owns what every such lane does the same way:

- staging: one `RemoteSession` per harness execution, its identity refreshed per generation;
- observe, as stream-then-reconcile: read the provider stream from the stored cursor, key every
  event by its id (or, for an id-less event, by its content), stop at the terminal event; a
  cursor the provider refuses replays the turn's stream once from the start; when retention
  has passed (`StreamExpired`) record one `stream.expired` status frame and stop asking the
  stream; once the stream ends or expired, the turn record is the terminal truth and becomes one
  synthesized final frame, and a turn still running after expiry is polled from the record at a
  bounded cadence with one status frame per change;
- dispatch reconciliation routed by the parsed dispatch key (`remote_session.dispatch`);
- later-turn texts, the continuation handover offer, and the rehydration receipt;
- the `429` capacity signal (`remote_session.errors`).

Each provider adapter supplies: the session record of its binding (`_new_session`), its event
source (`_events`; providers without native resume merge their history into it with
`stream.replay_then_stream`), an event classifier (`_classify`, the raw kinds of its
`KIND_TABLES` rows), a cursor codec (`cursors`), the turn-record reader, the final-frame key,
the create and send reconcilers, the closing-facts reader, and every request mapping (create,
send, cancel, usage).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Final, Literal, NamedTuple

from mission_control.adapters.remote_session.dispatch import (
    DispatchKeyParts,
    TurnAnchors,
    parse_dispatch_key,
)
from mission_control.adapters.remote_session.errors import (
    CapacityLimited,
    InvalidStreamCursor,
    StreamExpired,
    capacity_limited,
)
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import (
    STREAM_START,
    StreamCursorCodec,
    StreamOpened,
    TurnEventCursors,
)
from mission_control.adapters.remote_session.wake import SessionWake
from mission_control.application.execution.harness.controls import SessionHandover
from mission_control.application.execution.harness.dispatch import (
    DispatchLookup,
    DispatchRecord,
    ProviderCapacityLimited,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.application.frames.kinds import bounded_key
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.history_reconciliation import (
    HistoryReplayComplete,
    HistoryReplayIncomplete,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.execution.lanes import (
    HarnessRequest,
    LaneDescribe,
    LaneFrame,
    LaneProfileName,
    ObserveRequest,
    SessionHandle,
    TurnHandle,
)

# After `StreamExpired` a turn that is still running is reconciled through its record at this
# cadence, at most this many times per observe call (the segment bound still applies).
RECORD_POLL_INTERVAL_S: Final = 5.0
RECORD_POLL_LIMIT: Final = 120
FINAL_TEXT_FIELDS: Final = ("result", "text")

StreamOutcome = Literal["ended", "expired"]
EventRole = Literal["skip", "end", "frame", "terminal"]


class Classified(NamedTuple):
    """What one provider event is to the observe loop: `skip` (keep-alive, never stored),
    `end` (the stream is over), `frame` or `terminal` (stored under `raw_kind`)."""

    role: EventRole
    raw_kind: str = ""


@dataclass(frozen=True)
class ObservationNames:
    """The provider's words for the frames the observe loop writes itself."""

    record_source: str = "turn_record"
    final_kind: str = "turn.final"
    status_key: str = "turn-status"
    opened_key: str = "sse-open"
    expired_key: str = "sse-expired"
    content_key: str = "sse-content"


@dataclass(kw_only=True)
class RemoteSession:
    """Process-local state of one staged harness execution. Nothing here is authoritative:
    a reattach after a lost worker rebuilds it from the provider and the dispatch journal."""

    operation: OperationExecutionRequest
    identity: LaneExecutionIdentity
    session_ref: str | None = None
    session_url: str | None = None
    retention_seconds: int | None = None
    turns: TurnAnchors = field(default_factory=TurnAnchors)
    # The turns whose stream retention passed, with the cursor reached before it did.
    expired_streams: dict[str, str] = field(default_factory=dict)
    # Staged texts of later turns (a replacement, a continuation prompt) by instruction ref.
    turn_texts: dict[str, str] = field(default_factory=dict)
    handover: SessionHandover | None = None
    rehydrated: tuple[str, ...] = ()

    def record_rehydration(self, facts: list[str]) -> None:
        if facts:
            self.rehydrated = tuple(dict.fromkeys((*self.rehydrated, *facts)))


def terminal_text(
    body: Mapping[str, Any], fields: tuple[str, ...] = FINAL_TEXT_FIELDS
) -> str | None:
    """The first non-empty of `fields` in a terminal body, when it is text."""

    for name in fields:
        value = body.get(name)
        if value is not None and value != "":
            return value if isinstance(value, str) else None
    return None


class RemoteSessionLane[SessionT: RemoteSession](ABC):
    """Shared machinery of a Session Lane over a provider session API."""

    profile: ClassVar[LaneProfileName]
    terminal_statuses: ClassVar[frozenset[str]]
    names: ClassVar[ObservationNames] = ObservationNames()
    cursors: ClassVar[StreamCursorCodec] = TurnEventCursors()

    def __init__(
        self,
        *,
        describe: LaneDescribe,
        clock: Callable[[], datetime] | None = None,
        record_poll_interval_s: float = RECORD_POLL_INTERVAL_S,
        record_poll_limit: int = RECORD_POLL_LIMIT,
    ) -> None:
        if describe.lane_profile != self.profile:
            raise ValueError(f"{type(self).__name__} describes the {self.profile} profile")
        self._describe = describe
        self._clock = clock or (lambda: datetime.now(UTC))
        self._record_poll_interval_s = record_poll_interval_s
        self._record_poll_limit = record_poll_limit
        self._sessions: dict[str, SessionT] = {}

    def describe(self) -> LaneDescribe:
        return self._describe

    # --- staging ----------------------------------------------------------------------------

    @abstractmethod
    def _new_session(self, operation: OperationExecutionRequest) -> SessionT:
        """A fresh session for an operation this lane runs; `ValueError` for any other."""

    def stage(self, harness_execution_id: str, operation: OperationExecutionRequest) -> None:
        fresh = self._new_session(operation)
        current = self._sessions.get(harness_execution_id)
        if current is not None:
            if current.operation != operation:
                raise ValueError("harness execution is staged with another operation")
            return
        self._sessions[harness_execution_id] = fresh

    def _session(self, request: HarnessRequest) -> SessionT:
        session = self._sessions.get(request.harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {request.harness_execution_id} is not staged")
        if session.identity.attempt_no != request.generation:
            session.identity = LaneExecutionIdentity.of(
                session.operation, self.profile, request.generation
            )
        return session

    def rehydration_receipt(self, harness_execution_id: str) -> tuple[str, ...]:
        """Which non-persisted facts the last reattach re-applied (empty when nothing was)."""

        session = self._sessions.get(harness_execution_id)
        return () if session is None else session.rehydrated

    def wake_target(self, wake: SessionWake) -> str | None:
        """The staged harness execution a provider wake names; the caller re-reads it from
        the provider (observe, status), never from the webhook payload."""

        if wake.lane_profile != self.profile:
            return None
        for harness_execution_id, session in self._sessions.items():
            if session.session_ref == wake.resource_ref:
                return harness_execution_id
        return None

    # --- later turns and the continuation handover -----------------------------------------

    def stage_turn(self, harness_execution_id: str, instruction_ref: str, text: str) -> None:
        session = self._sessions.get(harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {harness_execution_id} is not staged")
        session.turn_texts[instruction_ref] = text

    async def pending_handover(self, harness_execution_id: str) -> SessionHandover | None:
        session = self._sessions.get(harness_execution_id)
        return None if session is None else session.handover

    async def complete_handover(self, harness_execution_id: str, transfer_id: str) -> None:
        session = self._sessions.get(harness_execution_id)
        if session is not None and session.handover is not None:
            if session.handover.transfer_id == transfer_id:
                session.session_ref = session.handover.session.native_session_ref
                session.handover = None

    def _capacity(self, error: CapacityLimited) -> ProviderCapacityLimited:
        return capacity_limited(error, lane_profile=self.profile, now=self._clock())

    # --- MP-06: reconcile an ambiguous create/send by native identity -----------------------

    async def reconcile_dispatch(
        self, record: DispatchRecord, *, session: SessionHandle | None
    ) -> DispatchLookup:
        parts = parse_dispatch_key(record.idempotency_key)
        if parts is None:
            return DispatchLookup(outcome="unknown", detail="the dispatch key names no execution")
        staged = self._sessions.get(parts.harness_execution_id)
        if record.kind == "create":
            return await self._reconcile_create(record, parts, staged)
        return await self._reconcile_send(record, parts, staged, session)

    @abstractmethod
    async def _reconcile_create(
        self, record: DispatchRecord, parts: DispatchKeyParts, staged: SessionT | None
    ) -> DispatchLookup:
        """Whether the provider holds the session a journaled create would have made."""

    @abstractmethod
    async def _reconcile_send(
        self,
        record: DispatchRecord,
        parts: DispatchKeyParts,
        staged: SessionT | None,
        session: SessionHandle | None,
    ) -> DispatchLookup:
        """Whether the provider accepted a journaled send (`TurnAnchors.lookup_latest`)."""

    # --- observe: stream, then reconcile from the turn record -------------------------------

    @abstractmethod
    def _events(
        self, session: SessionT, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        """The turn's events from the resume point `after` (None: from the start), led by the
        `StreamOpened` marker; raises `InvalidStreamCursor` or `StreamExpired` when the
        provider refuses the position."""

    @abstractmethod
    def _classify(self, event: SseEvent, body: Mapping[str, Any]) -> Classified:
        """The provider's event classifier."""

    @abstractmethod
    async def _read_turn(self, session_ref: str, turn_ref: str) -> Mapping[str, Any]:
        """The provider's turn record; `NativeTurnLost` when the turn no longer exists."""

    @abstractmethod
    def _final_key(self, turn_ref: str) -> str:
        """The dedupe key of the final frame synthesized from the turn record."""

    def _event_id(self, event: SseEvent, body: Mapping[str, Any]) -> str | None:
        del body
        return event.id

    def _turn_status(self, record: Mapping[str, Any]) -> str:
        return str(record.get("status") or "").lower()

    def _status_body(self, turn_ref: str, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "turn_ref": turn_ref,
            "status": record.get("status"),
            "observation": self.names.record_source,
        }

    def _tool_call_ref(self, raw_kind: str, body: Mapping[str, Any]) -> str | None:
        del raw_kind, body
        return None

    async def _on_terminal(self, session_ref: str, turn_ref: str, body: dict[str, Any]) -> None:
        """Annotate a terminal body before it is stored (default: nothing to add)."""

        del session_ref, turn_ref, body

    async def _on_history_terminal(
        self, session_ref: str, turn_ref: str, body: dict[str, Any]
    ) -> None:
        await self._on_terminal(session_ref, turn_ref, body)

    def _frame(
        self,
        request: ObserveRequest,
        *,
        key: str,
        cursor: str,
        raw_kind: str,
        body: dict[str, Any],
        turn_ref: str,
        terminal: bool = False,
    ) -> LaneFrame:
        return LaneFrame(
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            provider_key=key,
            cursor=cursor,
            kind=raw_kind,
            raw_kind=raw_kind,
            body=body,
            terminal=terminal,
            digest=sha256_digest(body),
            native_turn_ref=turn_ref,
            tool_call_ref=self._tool_call_ref(raw_kind, body),
        )

    async def observe(self, request: ObserveRequest) -> AsyncIterator[LaneFrame]:
        session = self._session(request)
        session_ref = request.turn.session.native_session_ref or session.session_ref
        turn_ref = request.turn.native_turn_ref
        if session_ref is None or turn_ref is None:
            raise NativeTurnLost("no provider turn to observe")
        after = self.cursors.resume_point(request.after, turn_ref)
        cursor = self.cursors.cursor(turn_ref, after) if after is not None else STREAM_START
        outcome: StreamOutcome = "expired" if turn_ref in session.expired_streams else "ended"
        if outcome == "ended":
            try:
                try:
                    async for frame in self._stream_frames(
                        request, session, session_ref, turn_ref, after
                    ):
                        cursor = frame.cursor
                        yield frame
                        if frame.terminal:
                            return
                except InvalidStreamCursor:
                    # Reopen once without the foreign cursor. This replay may itself report
                    # expired retention, which needs the same turn reconciliation.
                    async for frame in self._stream_frames(
                        request, session, session_ref, turn_ref, None
                    ):
                        cursor = frame.cursor
                        yield frame
                        if frame.terminal:
                            return
            except StreamExpired:
                # Retention passed: the backlog is gone, the turn is not. Record the fact
                # separately from whatever the turn record says and stop asking the stream.
                session.expired_streams[turn_ref] = cursor
                outcome = "expired"
                yield self._frame(
                    request,
                    key=bounded_key(self.names.expired_key, turn_ref, after or "start"),
                    cursor=cursor,
                    raw_kind="status",
                    body={
                        "stream": "expired",
                        "retention_seconds": session.retention_seconds,
                        "last_event_id": after,
                        "observation": self.names.record_source,
                    },
                    turn_ref=turn_ref,
                )
        async for frame in self._reconcile_turn(request, session_ref, turn_ref, cursor, outcome):
            yield frame

    async def _history_events(
        self, session: SessionT, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        raise HistoryReplayIncomplete("finite native history is unavailable")
        yield  # pragma: no cover

    async def reconcile_history(
        self, request: ObserveRequest
    ) -> AsyncIterator[LaneFrame | HistoryReplayComplete]:
        session = self._session(request)
        session_ref = request.turn.session.native_session_ref or session.session_ref
        turn_ref = request.turn.native_turn_ref
        if session_ref is None or turn_ref is None:
            raise NativeTurnLost("no provider turn to reconcile")
        after = self.cursors.resume_point(request.after, turn_ref)
        source = self._history_events(session, session_ref, turn_ref, after)
        async with aclosing(source):  # type: ignore[type-var]
            frames = self._stream_frames(
                request,
                session,
                session_ref,
                turn_ref,
                after,
                events=source,
                history=True,
            )
            async with aclosing(frames):  # type: ignore[type-var]
                async for frame in frames:
                    yield frame
        yield HistoryReplayComplete()

    async def _stream_frames(
        self,
        request: ObserveRequest,
        session: SessionT,
        session_ref: str,
        turn_ref: str,
        after: str | None,
        *,
        events: AsyncIterator[SseEvent | StreamOpened] | None = None,
        history: bool = False,
    ) -> AsyncIterator[LaneFrame]:
        cursor = self.cursors.cursor(turn_ref, after) if after is not None else STREAM_START
        source = (
            events if events is not None else self._events(session, session_ref, turn_ref, after)
        )
        async for item in source:
            if isinstance(item, StreamOpened):
                session.retention_seconds = item.retention_seconds
                yield self._frame(
                    request,
                    key=bounded_key(self.names.opened_key, turn_ref, after or "start"),
                    cursor=cursor,
                    raw_kind="status",
                    body={
                        "stream": "opened",
                        "retention_seconds": item.retention_seconds,
                        "last_event_id": item.last_event_id,
                    },
                    turn_ref=turn_ref,
                )
                continue
            body = item.json()
            role, raw_kind = self._classify(item, body)
            if role == "skip":
                continue  # keep-alive only; never persisted
            if role == "end":
                break
            event_id = self._event_id(item, body)
            if event_id is not None:
                cursor = self.cursors.cursor(turn_ref, event_id)
                key = self.cursors.provider_key(turn_ref, event_id)
            else:
                # An id-less event (a leading status re-sent on every reconnect) is keyed by
                # its content, so a replay stores it once.
                key = bounded_key(
                    self.names.content_key, raw_kind, turn_ref, sha256_digest(item.data)
                )
            terminal = role == "terminal"
            if terminal:
                if history:
                    await self._on_history_terminal(session_ref, turn_ref, body)
                else:
                    await self._on_terminal(session_ref, turn_ref, body)
            yield self._frame(
                request,
                key=key,
                cursor=cursor,
                raw_kind=raw_kind,
                body=body,
                turn_ref=turn_ref,
                terminal=terminal,
            )
            if terminal:
                return

    async def _reconcile_turn(
        self,
        request: ObserveRequest,
        session_ref: str,
        turn_ref: str,
        cursor: str,
        outcome: StreamOutcome,
    ) -> AsyncIterator[LaneFrame]:
        """The turn record is the terminal truth once the stream ended or expired: a terminal
        status becomes the one final frame; a running one is polled at a bounded cadence
        after expiry (a status frame per change), or left to the next segment."""

        polls = 0
        last_status: str | None = None
        while True:
            record = await self._read_turn(session_ref, turn_ref)
            status = self._turn_status(record)
            if status in self.terminal_statuses:
                body = dict(record)
                body["synthesized_from"] = self.names.record_source
                body["observation"] = {"source": self.names.record_source, "stream": outcome}
                await self._on_terminal(session_ref, turn_ref, body)
                yield self._frame(
                    request,
                    key=self._final_key(turn_ref),
                    cursor=cursor,
                    raw_kind=self.names.final_kind,
                    body=body,
                    turn_ref=turn_ref,
                    terminal=True,
                )
                return
            if outcome != "expired":
                return
            if status != last_status:
                last_status = status
                yield self._frame(
                    request,
                    key=bounded_key(self.names.status_key, turn_ref, status or "unknown"),
                    cursor=cursor,
                    raw_kind="status",
                    body=self._status_body(turn_ref, record),
                    turn_ref=turn_ref,
                )
            polls += 1
            if polls >= self._record_poll_limit:
                return
            await asyncio.sleep(self._record_poll_interval_s)

    # --- reading a terminal frame ------------------------------------------------------------

    @abstractmethod
    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts:
        """The provider's closing-facts reader over a terminal frame body."""

    def final_text(self, turn: TurnHandle, frame: LaneFrame) -> str | None:
        """`FinalTextLane` (MP-20): the turn's whole final text from the terminal frame body
        (the closing facts keep only a bounded excerpt of it). A provider whose terminal body
        names the text differently overrides this."""

        del turn
        return terminal_text(frame.body if isinstance(frame.body, Mapping) else {})

    def resume_cursor(self, provider_key: str) -> str | None:
        return self.cursors.resume_cursor(provider_key)


__all__ = [
    "FINAL_TEXT_FIELDS",
    "RECORD_POLL_INTERVAL_S",
    "RECORD_POLL_LIMIT",
    "Classified",
    "EventRole",
    "ObservationNames",
    "RemoteSession",
    "RemoteSessionLane",
    "StreamOutcome",
    "terminal_text",
]
