"""The `claude_managed` Lane Profile: Anthropic Managed Agents sessions (SPEC-06 section 4.2).

One Session Turn of a bound operation, driven by `lane.turn` over the Remote Session Lane base
(ADR-0052); the wire shapes are the pinned `anthropic` 1.13.0 source and the HL-23 smoke
(research/provider-smoke-2026-10.md):

- `prepare` syncs the composed pack (`ClaudeManagedPrepare`, HL-07): skills, the environment,
  the vault and the agent version, keyed by digest and read back. The binding's
  `materialization_digest` must be the pack's, and its `multiagent` must be what the pack's
  agent declares (`CAPABILITY_DRIFT` otherwise); a concurrent agent writer (`409`) is one
  re-sync. The receipt names the provider environment it delivered into
  (`provider_environment:<id>`), the delivery the launch readiness policy reads (MO-16);
- `start` creates the session on the pinned agent version, the environment and the vault, with
  the attempt budget (`budget.max_list_cost`, always set: it is also the only pause) and the
  dispatch metadata a lost create is reconciled by (there is no idempotency key: the agent's
  sessions are listed and matched on `mc_dispatch` client-side). The session starts idle; the
  first `user.message` is the first `send_turn`, so its event id is the native turn ref;
- `send_turn` sends one `user.message` only while the session is idle and waits on nothing: a
  message sent while running steers the current turn (Q-M1) and one sent while a tool waits on
  an answer or the budget is reached is refused (`400`), so both return `busy`
  (`wait_then_send`, ADR-0030);
- `observe` opens the session stream first, then replays the turn's history from the moment
  its message was processed and drops what the stream repeats (`frames.TurnFold`,
  `frames.ManagedEventCursors`); a reattached segment resumes from the position its last
  persisted frame names, so nothing is stored twice;
- `reattach` is native: the session lives at the provider; it is retrieved and observed again;
- `cancel_turn` sends `user.interrupt` without lifting a budget-gate hold;
  it waits until the session leaves `running`; the turn then closes `end_turn`, which
  `TurnFold` reads as `cancelled`. `interrupt_and_inject` is that cancel and a replacement
  `user.message` (`cancel_and_replace`);
- `hold_budget` is the emulated pause (SPEC-06 section 4.2): the cap is lowered to just above
  the spend, so every thread stops before its next model request (`budget_reached`), and
  restored to resume;
- `usage` settles the turn's tokens from its model requests and its cost from `list_cost`;
- `end_session` interrupts until idle, stages the session manifest (custody), archives the
  session and orders its deletion after the retention interval (SPEC-06 section 8;
  `ProviderSessionRetention`).

Mission Control custom tools, tool confirmations and publication are HL-09: a turn that waits
on one (`requires_action`) stays open here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from mission_control.adapters.anthropic_managed import frames
from mission_control.adapters.anthropic_managed.client import (
    AgentVersionConflict,
    JsonObject,
    ManagedAgentsClient,
)
from mission_control.adapters.anthropic_managed.cognition_points import MANAGED_POINT_RULES
from mission_control.adapters.anthropic_managed.describe import CLAUDE_MANAGED_DESCRIBE
from mission_control.adapters.anthropic_managed.pack import RenderedPack
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare, PreparedPack
from mission_control.adapters.anthropic_managed.tools import ManagedTools
from mission_control.adapters.cursor.local import LaneArtifactSink
from mission_control.adapters.remote_session.cognition_points import turn_points_for
from mission_control.adapters.remote_session.dispatch import (
    DispatchKeyParts,
    dispatch_metadata,
    lookup_created,
)
from mission_control.adapters.remote_session.errors import (
    CapacityLimited,
    RemoteSessionError,
    SessionNotFound,
)
from mission_control.adapters.remote_session.lane import (
    Classified,
    ObservationNames,
    RemoteSession,
    RemoteSessionLane,
)
from mission_control.adapters.remote_session.retention import ProviderSessionRetention
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import (
    StreamOpened,
    poll_while_idle,
    replay_then_stream,
)
from mission_control.adapters.remote_session.time_travel import seed_metadata, seed_turn_text
from mission_control.application.agentic_components.placement import (
    CAPABILITY_DRIFT,
    LaneProjectionError,
    turn_text,
)
from mission_control.application.execution.harness.dispatch import (
    DispatchLookup,
    DispatchRecord,
    SteerResult,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.points import TurnPointsRequest
from mission_control.application.execution.harness.protocol import (
    NativeTurnLost,
    UnsupportedHarnessOperations,
)
from mission_control.application.execution.harness.retention import (
    SessionDeletionOutcome,
    SessionRetentionService,
)
from mission_control.domain.execution.bindings import ClaudeManagedOptions, ProviderExecutionBinding
from mission_control.domain.execution.budget_controls import ManagedBudgetSnapshot
from mission_control.domain.execution.cognition_points import CognitionPointObservation
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.history_reconciliation import (
    MAX_HISTORY_FRAMES,
    HistoryReplayIncomplete,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.execution.lanes import (
    CancelReceipt,
    CancelTurnRequest,
    CleanupReceipt,
    EndSessionRequest,
    HarnessRequest,
    LaneDescribe,
    LaneFrame,
    LaneSeedHead,
    ObserveRequest,
    PreparedSession,
    PrepareRequest,
    ProviderStatus,
    ReattachRequest,
    SendTurnRequest,
    SessionHandle,
    StartRequest,
    StatusRequest,
    TurnHandle,
    UsageReport,
    UsageRequest,
)

PROFILE: Final = "claude_managed"
# The record states `_read_turn` reports for a closed turn (`TurnFold.summary` statuses).
_CLOSED: Final = frozenset({"finished", "cancelled", "error"})
# How often and how long a cancel or an end waits for the session to leave `running`.
IDLE_POLL_INTERVAL_S: Final = 1.0
IDLE_POLL_LIMIT: Final = 120
SESSION_TITLE_LIMIT: Final = 200
_NAMES: Final = ObservationNames(record_source="event_history", final_kind=frames.TURN_FINAL)


@dataclass(kw_only=True)
class _ManagedSession(RemoteSession):
    """`session_ref` is the Managed Agents session id; its turns are `user.message` events."""

    system: str = ""
    binding: ProviderExecutionBinding
    options: ClaudeManagedOptions
    pack: PreparedPack | None = None
    # The `processed_at` of each turn's message: where its history starts.
    turn_starts: dict[str, str] = field(default_factory=dict)
    # Each closed turn's summary (`frames.TurnFold.summary` plus its own cost).
    summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    interrupted: set[str] = field(default_factory=set)
    # The budget-gate pause: the lowered cap while held.
    held_cap: int | None = None
    active_stream: AsyncIterator[SseEvent | StreamOpened] | None = None
    # Cross-provider control: the seed head a forked unit's first turn continues from
    # (`PrepareRequest.seed` / `StartRequest.seed`), and the `user.message` ids a steer sent
    # into a running turn (never a turn of their own; `_reconcile_send` must not count them).
    seed: LaneSeedHead | None = None
    steers: dict[str, list[str]] = field(default_factory=dict)


class ClaudeManagedHarness(RemoteSessionLane[_ManagedSession], UnsupportedHarnessOperations):
    # `CancelledCloseLane`: `session.usage` precedes the idle after `user.interrupt` (OC-R3).
    cancelled_close: Final = "observe"
    """`claude_managed` Session Lane over `ManagedAgentsClient` (an HTTP fake in tests)."""

    profile = PROFILE
    terminal_statuses = _CLOSED
    names = _NAMES
    cursors = frames.ManagedEventCursors()

    def __init__(
        self,
        *,
        client: ManagedAgentsClient,
        preparer: ClaudeManagedPrepare,
        pack: RenderedPack | Callable[[OperationExecutionRequest], Awaitable[RenderedPack]],
        artifacts: LaneArtifactSink,
        retention: SessionRetentionService | None,
        labels: Mapping[str, str] | None = None,
        describe: LaneDescribe = CLAUDE_MANAGED_DESCRIBE,
        clock: Callable[[], datetime] | None = None,
        idle_poll_interval_s: float = IDLE_POLL_INTERVAL_S,
        idle_poll_limit: int = IDLE_POLL_LIMIT,
        tools: ManagedTools | None = None,
    ) -> None:
        super().__init__(describe=describe, clock=clock)
        self._client = client
        self._preparer = preparer
        self._pack = pack
        self._artifacts = artifacts
        self._retention = ProviderSessionRetention(retention, lane_profile=PROFILE)
        self._labels = dict(labels or {})
        self._idle_poll_interval_s = idle_poll_interval_s
        self._idle_poll_limit = idle_poll_limit
        self._tools = tools

    def _new_session(self, operation: OperationExecutionRequest) -> _ManagedSession:
        binding = ProviderExecutionBinding.carried_by(operation)
        if binding is None or binding.lane_profile != PROFILE:
            raise ValueError("claude_managed runs only an operation with a claude_managed binding")
        options = binding.provider_options
        assert isinstance(options, ClaudeManagedOptions)
        if options.multiagent and binding.repo_url is not None:
            # DECISIONS R33: subagents and workflows only on read-only knowledge work.
            raise ValueError("a claude_managed code mission keeps multiagent off")
            # TODO: FROM THE OWNER: We want multi agent even on code missions.
            # This needs to be changed.
        return _ManagedSession(
            operation=operation,
            binding=binding,
            options=options,
            identity=LaneExecutionIdentity.of(operation, PROFILE, 1),
        )

    def _by_ref(self, session_ref: str) -> _ManagedSession | None:
        for session in self._sessions.values():
            if session.session_ref == session_ref:
                return session
        return None

    @staticmethod
    def _ref(request_session: SessionHandle, session: _ManagedSession) -> str | None:
        return request_session.native_session_ref or session.session_ref

    def _handle(self, request: HarnessRequest, session: _ManagedSession) -> SessionHandle:
        assert session.session_ref is not None
        return SessionHandle(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            native_session_ref=session.session_ref,
        )

    # --- prepare, start, reattach, send -----------------------------------------------------

    async def prepare(self, request: PrepareRequest) -> PreparedSession:
        session = self._session(request)
        projected_pack = (
            self._pack
            if isinstance(self._pack, RenderedPack)
            else await self._pack(session.operation)
        )
        if session.binding.materialization_digest != projected_pack.materialization_digest:
            raise LaneProjectionError(
                CAPABILITY_DRIFT, "the composed pack is not the materialization the binding pins"
            )
        if (
            session.options.multiagent != projected_pack.pack.agent.multiagent
            or session.binding.model.model_id != projected_pack.pack.agent.model
        ):
            raise LaneProjectionError(
                CAPABILITY_DRIFT, "the binding's multiagent differs from the pack's agent"
            )
        try:
            pack = await self._preparer.sync(projected_pack)
        except AgentVersionConflict:
            # Another writer moved the agent between the read and the update: read it again.
            pack = await self._preparer.sync(projected_pack)
        session.system = projected_pack.system
        session.pack = pack
        if request.seed is not None:
            session.seed = request.seed
        return PreparedSession(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            workspace_ref=f"provider_environment:{pack.environment.environment_id}",
            projection_digests=pack.projection_digests(),
            materialization_ref=f"agent:{pack.agent.agent_id}@{pack.agent.version}",
        )

    async def start(self, request: StartRequest) -> SessionHandle:
        session = self._session(request)
        if session.pack is None:
            raise ValueError("start requires a prepared claude_managed session")
        identity = session.identity
        seed = request.seed or session.seed
        session.seed = seed
        body = {
            **session.pack.session_fields(),
            "budget": _budget(session.options.max_list_cost_minor_units),
            "title": f"mc {identity.run_key} {identity.attempt_no}"[:SESSION_TITLE_LIMIT],
            "metadata": {
                **dispatch_metadata(
                    run_key=identity.run_key,
                    generation=request.generation,
                    dispatch_key=request.idempotency_key,
                ),
                "mc_unit": identity.activation_key,
                # A seeded (forked) unit names the fork it continues; the session itself is
                # new: Managed Agents forks no session (`time_travel.py`).
                **seed_metadata(seed),
                # Drill scope labels (`mc_run=run1-<issue>`) are stamped last.
                **self._labels,
            },
        }
        instructions = "\n\n".join(
            segment.content
            for segment in session.operation.prompt_segments
            if segment.trust_class.value in {"system_authority", "authored_instruction"}
        )
        if instructions:
            body["agent"] = {
                "type": "agent_with_overrides",
                "id": session.pack.agent.agent_id,
                "version": session.pack.agent.version,
                "system": session.system + "\n\n" + instructions,
            }
        try:
            created = await self._client.create_session(body)
        except CapacityLimited as error:
            raise self._capacity(error) from error
        session.session_ref = str(created["id"])
        return self._handle(request, session)

    async def reattach(self, request: ReattachRequest) -> SessionHandle:
        session = self._session(request)
        try:
            record = await self._client.retrieve_session(request.native_session_ref)
        except SessionNotFound as error:
            raise NativeTurnLost("the managed session no longer exists") from error
        if record.get("archived_at"):
            raise NativeTurnLost("the managed session is archived")
        session.session_ref = str(record["id"])
        if request.native_turn_ref is not None:
            # The last turn the journal acknowledged: the anchor a lost send reconciles against.
            session.turns.anchor(request.native_turn_ref)
        return self._handle(request, session)

    async def send_turn(self, request: SendTurnRequest) -> TurnHandle:
        session = self._session(request)
        session_ref = self._ref(request.session, session)
        if session_ref is None:
            raise ValueError("send_turn requires a created managed session")
        if not await self._accepts_message(session_ref):
            return TurnHandle(session=request.session, turn_no=request.turn_no, status="busy")
        text = (
            session.turn_texts.get(request.instruction_ref)
            # A forked unit's first turn is the hydration prompt its seed staged.
            or (seed_turn_text(session.seed) if request.turn_no == 1 else None)
            or turn_text(session.operation, packet_on_disk=False)
            or "Execute the admitted operation instructions."
        )
        message = {"type": "user.message", "content": [{"type": "text", "text": text}]}
        try:
            (echo,) = await self._client.send_events(session_ref, [message])
        except CapacityLimited as error:
            raise self._capacity(error) from error
        turn_ref = str(echo["id"])
        session.turns.acknowledge(turn_ref, request.idempotency_key)
        return TurnHandle(
            session=request.session, turn_no=request.turn_no, native_turn_ref=turn_ref
        )

    async def steer(self, turn: TurnHandle, *, instruction_ref: str) -> SteerResult:
        """`SteeringLane`: a `user.message` sent while the session runs is consumed at the
        next model request of the **current** turn (Q-M1, HL-23), so it steers exactly that
        turn. Exact-target guard: the session must be `running` and the latest `user.message`
        must be the target turn (no later turn started); anything else is `stale_target`
        and the kernel requeues the command for the next boundary. The steer's own event id
        is remembered so a later send reconciliation never mistakes it for a turn."""

        session = self._sessions.get(turn.session.harness_execution_id)
        if session is None:
            return SteerResult(outcome="stale_target", detail="session is not staged")
        target = turn.native_turn_ref
        if target is None:
            return SteerResult(outcome="stale_target", detail="turn has no native identity")
        text = session.turn_texts.get(instruction_ref)
        if text is None:
            return SteerResult(outcome="stale_target", detail="instruction text not staged")
        session_ref = self._ref(turn.session, session)
        if session_ref is None:
            return SteerResult(outcome="stale_target", detail="no managed session")
        try:
            record = await self._client.retrieve_session(session_ref)
            if record.get("status") != "running":
                return SteerResult(
                    outcome="stale_target",
                    detail=f"session is {record.get('status') or 'unknown'}, not running",
                )
            latest = await self._latest_turn_message(session_ref, session)
            if latest != target:
                return SteerResult(
                    outcome="stale_target",
                    target_turn_ref=latest,
                    detail="the latest turn is not the target",
                )
            message = {"type": "user.message", "content": [{"type": "text", "text": text}]}
            (echo,) = await self._client.send_events(session_ref, [message])
        except SessionNotFound:
            return SteerResult(outcome="stale_target", detail="the managed session is gone")
        except RemoteSessionError as error:
            return SteerResult(outcome="stale_target", detail=f"refused: {error}"[:512])
        steer_id = str(echo["id"])
        session.steers.setdefault(target, []).append(steer_id)
        return SteerResult(outcome="applied", target_turn_ref=target)

    async def _latest_turn_message(self, session_ref: str, session: _ManagedSession) -> str | None:
        """The newest `user.message` that started a turn (steer messages skipped)."""

        steered = {steer for ids in session.steers.values() for steer in ids}
        async for message in self._client.list_events(
            session_ref, types=("user.message",), newest_first=True
        ):
            event_id = str(message.get("id") or "")
            if event_id and event_id not in steered:
                return event_id
        return None

    # --- cross-provider control: cognition points -------------------------------------------

    def turn_points(self, request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
        """`PointCollectingLane`: one `session_cursor` point per step boundary of the settled
        turn, from its persisted frames (`anthropic_managed.cognition_points`)."""

        return turn_points_for(request, MANAGED_POINT_RULES)

    async def _accepts_message(self, session_ref: str) -> bool:
        """Idle and waiting on nothing: a message then starts a turn of its own."""

        record = await self._client.retrieve_session(session_ref)
        if record.get("status") != "idle":
            return False
        return await self._last_stop_reason(session_ref) not in frames.WAITING_STOP_REASONS

    async def _last_stop_reason(self, session_ref: str) -> str | None:
        async for idle in self._client.list_events(
            session_ref, types=(frames.IDLE,), newest_first=True, limit=1
        ):
            return frames.stop_reason(idle)
        return None

    # --- MP-06: reconcile an ambiguous create/send ------------------------------------------

    async def _reconcile_create(
        self, record: DispatchRecord, parts: DispatchKeyParts, staged: _ManagedSession | None
    ) -> DispatchLookup:
        if staged is None or staged.pack is None:
            return DispatchLookup(
                outcome="unknown", detail="the create's agent is unknown to this process"
            )
        try:
            listed = await self._client.list_sessions(agent_id=staged.pack.agent.agent_id)
        except RemoteSessionError as error:
            return DispatchLookup(outcome="unknown", detail=str(error)[:512])
        found = lookup_created(listed, record.idempotency_key)
        if found.outcome == "found":
            staged.session_ref = found.native_ref
        return found

    async def _reconcile_send(
        self,
        record: DispatchRecord,
        parts: DispatchKeyParts,
        staged: _ManagedSession | None,
        session: SessionHandle | None,
    ) -> DispatchLookup:
        if staged is not None:
            remembered = staged.turns.sent.get(record.idempotency_key)
            if remembered is not None:
                return DispatchLookup(outcome="found", native_ref=remembered)
        session_ref = (session.native_session_ref if session is not None else None) or (
            staged.session_ref if staged is not None else None
        )
        if session_ref is None:
            return DispatchLookup(outcome="unknown", detail="no managed session to query")
        steered = {steer for ids in staged.steers.values() for steer in ids} if staged else set()
        try:
            messages = [
                str(event["id"])
                async for event in self._client.list_events(session_ref, types=("user.message",))
                if str(event["id"]) not in steered  # a steer is no turn of its own
            ]
        except RemoteSessionError as error:
            return DispatchLookup(outcome="unknown", detail=str(error)[:512])
        if parts.turn_no == 1 and len(messages) == 1:
            # Only this lane sends to its session: a lone message is the first turn.
            return DispatchLookup(outcome="found", native_ref=messages[0])
        if staged is None:
            return DispatchLookup(outcome="unknown", detail="no acknowledged turn anchors this")
        return staged.turns.lookup_latest(
            record.idempotency_key, messages[-1] if messages else None
        )

    # --- observe: the session stream, then the turn's history -------------------------------

    def _events(
        self, session: _ManagedSession, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        return self._turn_events(session, session_ref, turn_ref, after)

    async def _turn_events(
        self, session: _ManagedSession, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        """This turn's events from the stream and its history, each labelled with the raw kind
        `TurnFold` stores it under and keyed by its position; only events after `after`
        are yielded, but every one is folded."""

        fold = frames.TurnFold(turn_ref, interrupted=turn_ref in session.interrupted)
        resume = frames.parse_position(after) if after is not None else None

        async def history() -> AsyncIterator[SseEvent]:
            start = await self._turn_start(session, session_ref, turn_ref)
            if start is None:
                return  # not processed yet: the stream carries the whole turn
            async for body in self._client.list_events(session_ref, processed_from=start):
                yield SseEvent(event=str(body.get("type") or ""), data=json.dumps(body))

        session.active_stream = self._client.stream_events(session_ref)
        pending_idle: dict[str, Any] | None = None

        async def retry_pending() -> None:
            if self._tools is not None and pending_idle is not None:
                await self._tools.answer_pending(
                    session.operation, session.identity, session_ref, turn_ref, pending_idle
                )

        if self._tools is not None:
            session.active_stream = poll_while_idle(session.active_stream, retry_pending)
        stream = replay_then_stream(session.active_stream, history, _replay_key)
        async for item in stream:
            if isinstance(item, StreamOpened):
                yield item
                continue
            body = item.json()
            raw_kind = fold.observe(body)
            if raw_kind is None:
                continue
            position = frames.event_position(body)
            if resume is not None:
                # Up to and including the resumed position everything is already stored.
                parsed = frames.parse_position(position) if position is not None else None
                if parsed is None or parsed[0] < resume[0]:
                    continue
                if parsed == resume:
                    resume = None
                    continue
                if parsed[0] == resume[0]:
                    continue
                resume = None
            if fold.closes(raw_kind, body):
                session.summaries[turn_ref] = fold.summary(raw_kind, body)
            yield SseEvent(event=raw_kind, data=item.data, id=position)
            if raw_kind == frames.IDLE and self._tools is not None:
                pending_idle = body
                await self._tools.answer_pending(
                    session.operation, session.identity, session_ref, turn_ref, body
                )

    async def _history_events(
        self, session: _ManagedSession, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        start = await self._turn_start(
            session, session_ref, turn_ref, max_events=MAX_HISTORY_FRAMES
        )
        if start is None:
            raise HistoryReplayIncomplete("native turn is not processed")
        fold = frames.TurnFold(turn_ref, interrupted=turn_ref in session.interrupted)
        resume = frames.parse_position(after) if after is not None else None
        scanned = 0
        async for body in self._client.list_events(session_ref, processed_from=start):
            scanned += 1
            if scanned > MAX_HISTORY_FRAMES:
                raise HistoryReplayIncomplete("native history frame bound")
            raw_kind = fold.observe(body)
            if raw_kind is None:
                continue
            position = frames.event_position(body)
            if resume is not None:
                parsed = frames.parse_position(position) if position is not None else None
                if parsed is None or parsed[0] < resume[0]:
                    continue
                if parsed == resume:
                    resume = None
                    continue
                if parsed[0] == resume[0]:
                    continue
                resume = None
            if fold.closes(raw_kind, body):
                session.summaries[turn_ref] = fold.summary(raw_kind, body)
            yield SseEvent(event=raw_kind, data=json.dumps(body), id=position)
        if resume is not None:
            raise HistoryReplayIncomplete("native resume position was not found")

    async def observe(self, request: ObserveRequest) -> AsyncIterator[LaneFrame]:
        session = self._session(request)
        try:
            async for frame in super().observe(request):
                yield frame
        finally:
            stream, session.active_stream = session.active_stream, None
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    async def _turn_start(
        self, session: _ManagedSession, session_ref: str, turn_ref: str, *, max_events: int = 0
    ) -> str | None:
        """When the turn's message was processed (None while it is still queued)."""

        start = session.turn_starts.get(turn_ref)
        if start is None:
            scanned = 0
            async for message in self._client.list_events(session_ref, types=("user.message",)):
                scanned += 1
                if max_events and scanned > max_events:
                    raise HistoryReplayIncomplete("native turn lookup bound")
                if message.get("id") == turn_ref and message.get("processed_at"):
                    start = str(message["processed_at"])
                    session.turn_starts[turn_ref] = start
                    break
        return start

    def _classify(self, event: SseEvent, body: Mapping[str, Any]) -> Classified:
        closing = event.event == frames.TERMINATED or (
            event.event == frames.IDLE and frames.stop_reason(body) in frames.ENDING_STOP_REASONS
        )
        return Classified("terminal" if closing else "frame", event.event)

    async def _read_turn(self, session_ref: str, turn_ref: str) -> Mapping[str, Any]:
        """The turn's close read from the event history when the stream ended without it."""

        session = self._by_ref(session_ref)
        if session is not None and turn_ref in session.summaries:
            summary = session.summaries[turn_ref]
            return {"status": summary["status"], frames.SUMMARY_KEY: summary}
        try:
            record = await self._client.retrieve_session(session_ref)
        except SessionNotFound as error:
            raise NativeTurnLost("the managed session no longer exists") from error
        start = None if session is None else await self._turn_start(session, session_ref, turn_ref)
        if session is not None and start is not None:
            fold = frames.TurnFold(turn_ref, interrupted=turn_ref in session.interrupted)
            async for body in self._client.list_events(session_ref, processed_from=start):
                raw_kind = fold.observe(body)
                if raw_kind is not None and fold.closes(raw_kind, body):
                    summary = fold.summary(raw_kind, body)
                    return {"status": summary["status"], frames.SUMMARY_KEY: summary}
        return {"status": record.get("status")}

    def _final_key(self, turn_ref: str) -> str:
        return frames.final_key(turn_ref)

    def _status_body(self, turn_ref: str, record: Mapping[str, Any]) -> dict[str, Any]:
        return {"turn_ref": turn_ref, "status": record.get("status"), "observation": "session"}

    def _tool_call_ref(self, raw_kind: str, body: Mapping[str, Any]) -> str | None:
        return frames.tool_call_ref(raw_kind, body)

    async def _on_terminal(self, session_ref: str, turn_ref: str, body: dict[str, Any]) -> None:
        """Write the turn summary on its closing frame, with the turn's own cost: the
        session's `list_cost` at the close less the last one reported before the turn."""

        session = self._by_ref(session_ref)
        summary = dict(body.get(frames.SUMMARY_KEY) or {})
        if not summary and session is not None:
            summary = dict(session.summaries.get(turn_ref) or {})
        reached = summary.get("list_cost")
        start = summary.get("started_at")
        if isinstance(reached, int) and isinstance(start, str):
            before = await self._list_cost_before(session_ref, start)
            summary["list_cost_minor_units"] = max(0, reached - before)
        body[frames.SUMMARY_KEY] = summary
        if session is not None:
            session.summaries[turn_ref] = summary

    async def _list_cost_before(self, session_ref: str, start: str) -> int:
        async for snapshot in self._client.list_events(
            session_ref,
            types=("session.usage",),
            processed_before=start,
            newest_first=True,
            limit=1,
        ):
            return frames.list_cost_minor_units(snapshot.get("usage")) or 0
        return 0

    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts:
        return frames.closing_facts(frame.body if isinstance(frame.body, Mapping) else {})

    def final_text(self, turn: TurnHandle, frame: LaneFrame) -> str | None:
        return frames.final_text(frame.body if isinstance(frame.body, Mapping) else {})

    # --- controls ---------------------------------------------------------------------------

    async def status(self, request: StatusRequest) -> ProviderStatus:
        session = self._session(request)
        session_ref = self._ref(request.session, session)
        if session_ref is None:
            return ProviderStatus(status="not_started", terminal=False, idle=True)
        try:
            record = await self._client.retrieve_session(session_ref)
        except SessionNotFound as error:
            raise NativeTurnLost("the managed session no longer exists") from error
        status = str(record.get("status") or "")
        if status == "terminated":
            return ProviderStatus(status=status, terminal=True, idle=True)
        if status != "idle":
            return ProviderStatus(status=status, terminal=False, idle=False)
        reason = await self._last_stop_reason(session_ref)
        return ProviderStatus(
            status=reason or status,
            terminal=request.turn is not None and reason in frames.ENDING_STOP_REASONS,
            idle=reason not in frames.WAITING_STOP_REASONS,
        )

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt:
        session = self._session(request)
        session_ref = self._ref(request.turn.session, session)
        turn_ref = request.turn.native_turn_ref
        if session_ref is None or turn_ref is None:
            return CancelReceipt(acknowledged=True, already_terminal=True, native_status="idle")
        try:
            record = await self._client.retrieve_session(session_ref)
            if record.get("status") == "terminated":
                return CancelReceipt(
                    acknowledged=True, already_terminal=True, native_status="terminated"
                )
            if record.get("status") == "idle":
                reason = await self._last_stop_reason(session_ref)
                if reason == "budget_reached":
                    return CancelReceipt(acknowledged=False, native_status="budget_reached")
                if reason in frames.ENDING_STOP_REASONS:
                    return CancelReceipt(
                        acknowledged=True, already_terminal=True, native_status=reason
                    )
            await self._interrupt(session, session_ref, turn_ref)
            status = await self._until_settled(session_ref)
        except SessionNotFound:
            return CancelReceipt(acknowledged=False, native_status="unknown")
        return CancelReceipt(acknowledged=True, native_status=status)

    async def _interrupt(
        self, session: _ManagedSession, session_ref: str, turn_ref: str | None
    ) -> None:
        # Never lift a cap to interrupt: updates can automatically resume cognition.
        # A held turn keeps its liability until native terminal evidence is observed.
        if turn_ref is not None:
            session.interrupted.add(turn_ref)
        await self._client.send_events(session_ref, [{"type": "user.interrupt"}])

    async def _until_settled(self, session_ref: str) -> str:
        """The session's status once it left `running` (bounded; the status lags the idle
        event, HL-23 client pattern 6)."""

        status = "running"
        for _poll in range(self._idle_poll_limit):
            record = await self._client.retrieve_session(session_ref)
            status = str(record.get("status") or "")
            if status not in {"running", "rescheduling"}:
                return status
            await asyncio.sleep(self._idle_poll_interval_s)
        return status

    async def hold_budget(self, harness_execution_id: str, held: bool) -> int:
        """The emulated pause (budget gate): lower the session's cap to one minor unit above
        its spend, so it stops before its next model request (`budget_reached`); release it
        by restoring the binding's cap. Returns the cap now set."""

        session = self._sessions.get(harness_execution_id)
        if session is None or session.session_ref is None:
            raise NativeTurnLost(f"harness execution {harness_execution_id} has no session")
        if not held:
            cap = session.options.max_list_cost_minor_units
            await self._set_cap(session.session_ref, cap)
            session.held_cap = None
            return cap
        record = await self._client.retrieve_session(session.session_ref)
        usage = record.get("usage")
        if not isinstance(usage, Mapping):
            raise ValueError("Managed session cost is unknown")
        spent = _strict_usd_minor_units(usage.get("list_cost"))
        cap = min(spent + 1, session.options.max_list_cost_minor_units)
        await self._set_cap(session.session_ref, cap)
        session.held_cap = cap
        return cap

    async def _set_cap(self, session_ref: str, cap: int) -> None:
        await self._client.update_session(session_ref, {"budget": _budget(cap)})

    async def set_budget(self, native_session_ref: str, cap_minor_units: int) -> None:
        """One governed POST. The caller owns the durable intent and immutable ceiling."""
        await self._set_cap(native_session_ref, cap_minor_units)

    async def read_budget(self, native_session_ref: str) -> ManagedBudgetSnapshot:
        record = await self._client.retrieve_session(native_session_ref)
        budget = record.get("budget")
        usage = record.get("usage")
        if not isinstance(budget, Mapping) or budget.get("type") != "limit":
            raise ValueError("Managed session has no readable finite budget")
        if not isinstance(usage, Mapping):
            raise ValueError("Managed session cost is unknown")
        cap = _strict_usd_minor_units(budget.get("max_list_cost"))
        spent = _strict_usd_minor_units(usage.get("list_cost"))
        reason, evidence = None, ""
        async for idle in self._client.list_events(
            native_session_ref, types=(frames.IDLE,), newest_first=True, limit=1
        ):
            reason, evidence = frames.stop_reason(idle), frames.event_position(idle) or ""
            break
        observed = record.get("status") == "idle" and reason == "budget_reached" and bool(evidence)
        return ManagedBudgetSnapshot(
            cap_minor_units=cap,
            spent_minor_units=spent,
            boundary_observed=observed,
            evidence=evidence,
            disposition=(
                "budget_boundary"
                if observed
                else "requires_action"
                if reason == "requires_action" and record.get("status") == "idle"
                else "terminal"
                if record.get("status") == "terminated"
                or (record.get("status") == "idle" and reason in frames.ENDING_STOP_REASONS)
                else "running"
            ),
        )

    async def usage(self, request: UsageRequest) -> UsageReport:
        """The turn's settled usage once it closed; `unknown` otherwise (never zero)."""

        session = self._session(request)
        turn_ref = request.turn.native_turn_ref if request.turn is not None else None
        summary = session.summaries.get(turn_ref) if turn_ref is not None else None
        return frames.turn_usage(summary) if summary else UsageReport(disposition="unknown")

    # --- end ----------------------------------------------------------------------------------

    async def end_session(self, request: EndSessionRequest) -> CleanupReceipt:
        session = self._session(request)
        session_ref = self._ref(request.session, session)
        if session_ref is None:
            self._sessions.pop(request.harness_execution_id, None)
            return CleanupReceipt(released=False)
        try:
            record = await self._client.retrieve_session(session_ref)
            if record.get("status") in {"running", "rescheduling"}:
                await self._interrupt(session, session_ref, None)
                await self._until_settled(session_ref)
            manifest_ref = await self._stage_manifest(session, request, session_ref, record)
            if not record.get("archived_at"):
                await self._client.archive_session(session_ref)
        except SessionNotFound:
            self._sessions.pop(request.harness_execution_id, None)
            return CleanupReceipt(released=False)
        # The transcript is not ZDR-eligible: delete it once the retention interval passes.
        await self._retention.after_custody(session.identity, session_ref)
        self._sessions.pop(request.harness_execution_id, None)
        return CleanupReceipt(released=True, artifact_refs=(manifest_ref,))

    async def _stage_manifest(
        self,
        session: _ManagedSession,
        request: EndSessionRequest,
        session_ref: str,
        record: JsonObject,
    ) -> str:
        identity = session.identity
        pack = session.pack
        manifest = {
            "schema_version": "mc.managed_session_capture.v1",
            "captured_at": self._clock().isoformat(),
            "provenance": {
                "request_scope": identity.request_scope,
                "run_id": identity.run_key,
                "activation_key": identity.activation_key,
                "attempt_no": identity.attempt_no,
                "harness_execution_id": request.harness_execution_id,
                "generation": request.generation,
                "lane_profile": PROFILE,
                "provider_session_ref": session_ref,
            },
            "agent": record.get("agent"),
            "environment_id": record.get("environment_id"),
            "materialization_digest": pack.agent.materialization_digest if pack else None,
            "budget": record.get("budget"),
            "usage": record.get("usage"),
            "turns": {
                turn: {
                    key: summary.get(key)
                    for key in ("status", "stop_reason", "usage", "list_cost_minor_units")
                }
                for turn, summary in sorted(session.summaries.items())
            },
            "observed_turn_refs": sorted(session.turns.observed()),
        }
        return await self._artifacts.stage(
            request_scope=identity.request_scope,
            name=f"claude-managed/{request.harness_execution_id}/{request.generation}"
            "/session-manifest.json",
            content=json.dumps(manifest, sort_keys=True, default=str).encode("utf-8"),
            media_type="application/json",
        )


class ManagedSessionDeleter:
    """The `claude_managed` `HostedSessionDeleter`: deletes a session once its retention
    interval passed (`absent` when the provider no longer has it)."""

    def __init__(self, client: ManagedAgentsClient) -> None:
        self._client = client

    async def delete_session(self, session_ref: str) -> SessionDeletionOutcome:
        try:
            await self._client.delete_session(session_ref)
        except SessionNotFound:
            return "absent"
        return "deleted"


def _strict_usd_minor_units(value: object) -> int:
    if not isinstance(value, Mapping) or value.get("currency") != "USD":
        raise ValueError("Managed cost/cap requires explicit USD")
    amount = value.get("amount")
    if not isinstance(amount, str) or not amount or not amount.isascii() or not amount.isdigit():
        raise ValueError("Managed cost/cap is unknown or malformed")
    return int(amount)


def _budget(cap_minor_units: int) -> dict[str, Any]:
    return {
        "type": "limit",
        "max_list_cost": {"amount": str(cap_minor_units), "currency": "USD"},
    }


def _replay_key(event: SseEvent) -> str | None:
    """Stream and history name one event by its id and whether it was processed (a client
    event is streamed queued, then processed)."""

    body = event.json()
    event_id = body.get("id")
    if not event_id:
        return None
    return f"{event_id}:{'processed' if body.get('processed_at') else 'queued'}"


__all__ = ["PROFILE", "ClaudeManagedHarness", "ManagedSessionDeleter"]
