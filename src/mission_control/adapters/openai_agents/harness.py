"""Codex harness over OpenAI Agents API sessions (SPEC-06 section 5.2).

The stream has no replay. Every subscription first restores durable items and
pending actions, then applies buffered notifications. Only root turn terminal
records settle execution; idle and environment state are observations.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from mission_control.adapters.cursor.local import LaneArtifactSink
from mission_control.adapters.openai_agents import frames
from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.openai_agents.cognition_points import AGENTS_POINT_RULES
from mission_control.adapters.openai_agents.describe import CODEX_AGENTS_DESCRIBE
from mission_control.adapters.openai_agents.pack import CodexAgentsPack
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer, PreparedCodexAgents
from mission_control.adapters.openai_agents.tools import AgentsTools
from mission_control.adapters.remote_session.cognition_points import turn_points_for
from mission_control.adapters.remote_session.dispatch import (
    DispatchKeyParts,
    dispatch_metadata,
    lookup_created,
)
from mission_control.adapters.remote_session.errors import (
    CapacityLimited,
    RemoteSessionError,
    SessionBusy,
    SessionNotFound,
)
from mission_control.adapters.remote_session.lane import (
    Classified,
    RemoteSession,
    RemoteSessionLane,
)
from mission_control.adapters.remote_session.retention import ProviderSessionRetention
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import (
    StreamOpened,
    TurnEventCursors,
    poll_while_idle,
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
from mission_control.domain.execution.bindings import CodexAgentsOptions, ProviderExecutionBinding
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

PROFILE: Final = "codex_agents"


@dataclass(kw_only=True)
class _AgentsSession(RemoteSession):
    binding: ProviderExecutionBinding
    pack: PreparedCodexAgents | None = None
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    stream: AsyncIterator[SseEvent | StreamOpened] | None = None
    opened: StreamOpened | None = None
    active_stream: AsyncIterator[SseEvent | StreamOpened] | None = None
    # Cross-provider control: the seed head a forked unit's first turn continues from.
    seed: LaneSeedHead | None = None


class CodexAgentsHarness(RemoteSessionLane[_AgentsSession], UnsupportedHarnessOperations):
    # `CancelledCloseLane`: the cancelled session input reports its close and usage (OC-R3).
    cancelled_close: Final = "observe"
    profile = PROFILE
    terminal_statuses = frames.TERMINAL
    cursors = TurnEventCursors("agents")

    def __init__(
        self,
        *,
        client: AgentsApiClient,
        preparer: CodexAgentsPreparer,
        pack: CodexAgentsPack | Callable[[OperationExecutionRequest], Awaitable[CodexAgentsPack]],
        artifacts: LaneArtifactSink,
        retention: SessionRetentionService | None,
        labels: Mapping[str, str] | None = None,
        tools: AgentsTools | None = None,
        poll_interval_s: float = 0.25,
        poll_limit: int = 120,
    ) -> None:
        super().__init__(describe=CODEX_AGENTS_DESCRIBE)
        self._client, self._preparer, self._pack = client, preparer, pack
        self._tools = tools
        self._artifacts = artifacts
        self._retention = ProviderSessionRetention(retention, lane_profile=PROFILE)
        self._labels = dict(labels or {})
        if {"mc_dispatch", "mc_generation", "mc_unit"} & self._labels.keys():
            raise ValueError("labels cannot replace dispatch identity")
        self._poll_interval_s, self._poll_limit = poll_interval_s, poll_limit

    def _new_session(self, operation: OperationExecutionRequest) -> _AgentsSession:
        binding = ProviderExecutionBinding.carried_by(operation)
        if binding is None or binding.lane_profile != PROFILE:
            raise ValueError("codex_agents requires its exact provider binding")
        options = binding.provider_options
        assert isinstance(options, CodexAgentsOptions)
        if options.multi_agent and binding.repo_url is not None:
            raise ValueError("code missions keep multi_agent off")
        return _AgentsSession(
            operation=operation,
            binding=binding,
            identity=LaneExecutionIdentity.of(operation, PROFILE, 1),
        )

    def _by_ref(self, session_ref: str) -> _AgentsSession | None:
        return next(
            (value for value in self._sessions.values() if value.session_ref == session_ref), None
        )

    def _handle(self, request: HarnessRequest, session: _AgentsSession) -> SessionHandle:
        return SessionHandle(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            native_session_ref=session.session_ref,
        )

    async def prepare(self, request: PrepareRequest) -> PreparedSession:
        session = self._session(request)
        projected_pack = (
            self._pack
            if isinstance(self._pack, CodexAgentsPack)
            else await self._pack(session.operation)
        )
        options = session.binding.provider_options
        assert isinstance(options, CodexAgentsOptions)
        if (
            session.binding.materialization_digest != projected_pack.digest
            or options.multi_agent != projected_pack.document.agent.multi_agent
            or session.binding.model.model_id != projected_pack.document.agent.model
        ):
            raise LaneProjectionError(
                CAPABILITY_DRIFT, "the composed pack differs from the sealed binding"
            )
        session.pack = await self._preparer.sync(projected_pack)
        if request.seed is not None:
            session.seed = request.seed
        return PreparedSession(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            workspace_ref=f"provider_environment:{session.pack.template.id}",
            projection_digests={
                resource.kind: resource.readback_digest for resource in session.pack.resources
            },
            materialization_ref=f"agent:{session.pack.agent.id}",
        )

    async def start(self, request: StartRequest) -> SessionHandle:
        session = self._session(request)
        if session.pack is None:
            raise ValueError("start requires a prepared Agents API session")
        seed = request.seed or session.seed
        session.seed = seed
        metadata = {
            **dispatch_metadata(
                run_key=session.identity.run_key,
                generation=request.generation,
                dispatch_key=request.idempotency_key,
            ),
            "mc_unit": session.identity.activation_key,
            # A seeded (forked) unit names the fork it continues; the session itself is new:
            # the Agents API forks no session (`time_travel.py`, OA-D4).
            **seed_metadata(seed),
            **self._labels,
        }
        try:
            record = await self._client.create_session(
                {
                    "agent_id": session.pack.agent.id,
                    "agent": {
                        "instructions": "\n\n".join(
                            segment.content
                            for segment in session.operation.prompt_segments
                            if segment.trust_class.value
                            in {"system_authority", "authored_instruction"}
                        )
                    },
                    "environment": session.pack.session_environment(),
                    "vault_ids": session.pack.vault_ids,
                    "metadata": metadata,
                }
            )
        except CapacityLimited as error:
            raise self._capacity(error) from error
        session.session_ref = str(record["id"])
        return self._handle(request, session)

    async def reattach(self, request: ReattachRequest) -> SessionHandle:
        session = self._session(request)
        try:
            await self._client.retrieve_session(request.native_session_ref)
        except SessionNotFound as error:
            raise NativeTurnLost("the Agents API session no longer exists") from error
        session.session_ref = request.native_session_ref
        if request.native_turn_ref:
            session.turns.anchor(request.native_turn_ref)
        return self._handle(request, session)

    async def _root_turns(self, session_ref: str) -> list[dict[str, Any]]:
        return [
            turn
            async for turn in self._client.turns(session_ref)
            if turn.get("subagent_id") is None
        ]

    async def _initial_action_turn(self, session_ref: str) -> str | None:
        """An initial, exclusively owned idle-session dispatch can use exact action custody.

        This is never a later-turn or recovery guess: the caller retains the empty
        pre-send root history and successful input submission in this process.
        """
        state = await self._client.retrieve_session(session_ref)
        actions = state.get("required_actions", [])
        if state.get("status") != "requires_action" or len(actions) != 1:
            return None
        turn_ref = actions[0].get("turn_id")
        if not isinstance(turn_ref, str) or not turn_ref:
            return None
        turn = await self._client.retrieve_turn(session_ref, turn_ref)
        if (
            turn.get("id") != turn_ref
            or turn.get("session_id") != session_ref
            or turn.get("subagent_id") is not None
            or turn.get("status") not in {"waiting", "in_progress"}
        ):
            return None
        return turn_ref

    async def send_turn(self, request: SendTurnRequest) -> TurnHandle:
        session = self._session(request)
        session_ref = request.session.native_session_ref or session.session_ref
        if session_ref is None:
            raise ValueError("send_turn requires a created Agents API session")
        record = await self._client.retrieve_session(session_ref)
        if record.get("status") != "idle" or record.get("required_actions"):
            return TurnHandle(session=request.session, turn_no=request.turn_no, status="busy")
        await self._close_stream(session)
        before = {str(turn["id"]) for turn in await self._root_turns(session_ref)}
        text = (
            session.turn_texts.get(request.instruction_ref)
            # A forked unit's first turn is the hydration prompt its seed staged.
            or (seed_turn_text(session.seed) if request.turn_no == 1 else None)
            or turn_text(session.operation, packet_on_disk=False)
            or "Execute the admitted operation instructions."
        )
        event = _input_message(text)
        # Subscribe before dispatch. The provider does not replay early notifications.
        session.stream = self._client.stream_events(session_ref)
        opened = await anext(session.stream)
        if not isinstance(opened, StreamOpened):
            raise RemoteSessionError("Agents API stream did not confirm subscription")
        session.opened = opened
        try:
            await self._client.send_events(
                session_ref, [event], idempotency_key=request.idempotency_key
            )
        except SessionBusy:
            await self._close_stream(session)
            return TurnHandle(session=request.session, turn_no=request.turn_no, status="busy")
        except CapacityLimited as error:
            await self._close_stream(session)
            raise self._capacity(error) from error
        for _ in range(self._poll_limit):
            new = [turn for turn in await self._root_turns(session_ref) if turn["id"] not in before]
            if len(new) == 1:
                turn_ref = str(new[0]["id"])
                session.turns.acknowledge(turn_ref, request.idempotency_key)
                return TurnHandle(
                    session=request.session, turn_no=request.turn_no, native_turn_ref=turn_ref
                )
            if not new and request.turn_no == 1 and not before:
                action_turn = await self._initial_action_turn(session_ref)
                if action_turn is not None:
                    session.turns.acknowledge(action_turn, request.idempotency_key)
                    return TurnHandle(
                        session=request.session,
                        turn_no=request.turn_no,
                        native_turn_ref=action_turn,
                    )
            if len(new) > 1:
                break  # Never guess which of several accepted turns belongs to this dispatch.
            await asyncio.sleep(self._poll_interval_s)
        raise RemoteSessionError("accepted Agents API input has no unambiguous turn yet")

    async def steer(self, turn: TurnHandle, *, instruction_ref: str) -> SteerResult:
        """`SteeringLane`: input sent while the session is `in_progress` steers the active
        turn (HL-23: it lands as a `message:user` item of the same turn, before its
        `final_answer`). The API has no expected-turn compare-and-swap (OA-D5), so the
        guard is a read before and after: the session must be `in_progress` with no
        required action and the latest root turn must be the target; after the send a new
        root turn means the input started a turn instead and the steer is `stale_target`
        (its effects are reported, never hidden). `active_turn_not_steerable` (`409`) is
        `stale_target` too: the kernel requeues the command for the next boundary."""

        session = self._sessions.get(turn.session.harness_execution_id)
        if session is None:
            return SteerResult(outcome="stale_target", detail="session is not staged")
        target = turn.native_turn_ref
        if target is None:
            return SteerResult(outcome="stale_target", detail="turn has no native identity")
        text = session.turn_texts.get(instruction_ref)
        if text is None:
            return SteerResult(outcome="stale_target", detail="instruction text not staged")
        ref = turn.session.native_session_ref or session.session_ref
        if ref is None:
            return SteerResult(outcome="stale_target", detail="no Agents API session")
        try:
            record = await self._client.retrieve_session(ref)
            if record.get("status") != "in_progress" or record.get("required_actions"):
                return SteerResult(
                    outcome="stale_target",
                    detail=f"session is {record.get('status') or 'unknown'}, not in progress",
                )
            before = await self._root_turns(ref)
            latest = str(before[-1]["id"]) if before else None
            if latest != target:
                return SteerResult(
                    outcome="stale_target",
                    target_turn_ref=latest,
                    detail="the latest root turn is not the target",
                )
            await self._client.send_events(
                ref,
                [_input_message(text)],
                idempotency_key=f"{instruction_ref}:steer:{target}"[:512],
            )
            after = [str(item["id"]) for item in await self._root_turns(ref)]
        except SessionBusy:
            return SteerResult(outcome="stale_target", detail="active_turn_not_steerable")
        except SessionNotFound:
            return SteerResult(outcome="stale_target", detail="the Agents API session is gone")
        except RemoteSessionError as error:
            return SteerResult(outcome="stale_target", detail=f"refused: {error}"[:512])
        started = [item for item in after if item not in {str(t["id"]) for t in before}]
        if started:
            return SteerResult(
                outcome="stale_target",
                target_turn_ref=started[0],
                detail="the input started a new turn instead of steering the target",
            )
        return SteerResult(outcome="applied", target_turn_ref=target)

    # --- cross-provider control: cognition points -------------------------------------------

    def turn_points(self, request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
        """`PointCollectingLane`: one `thread_item` point per step boundary of the settled
        turn, from its persisted frames (`openai_agents.cognition_points`)."""

        return turn_points_for(request, AGENTS_POINT_RULES)

    async def _reconcile_create(
        self, record: DispatchRecord, parts: DispatchKeyParts, staged: _AgentsSession | None
    ) -> DispatchLookup:
        if staged is None or staged.pack is None:
            return DispatchLookup(
                outcome="unknown", detail="the create's saved agent is unavailable"
            )
        listed = [session async for session in self._client.sessions(staged.pack.agent.id)]
        found = lookup_created(listed, record.idempotency_key)
        if found.outcome == "found":
            staged.session_ref = found.native_ref
        return found

    async def _reconcile_send(
        self,
        record: DispatchRecord,
        parts: DispatchKeyParts,
        staged: _AgentsSession | None,
        session: SessionHandle | None,
    ) -> DispatchLookup:
        if staged is None:
            return DispatchLookup(outcome="unknown", detail="no staged turn anchor")
        remembered = staged.turns.sent.get(record.idempotency_key)
        if remembered:
            return DispatchLookup(outcome="found", native_ref=remembered)
        ref = (session.native_session_ref if session else None) or staged.session_ref
        if ref is None:
            return DispatchLookup(outcome="unknown", detail="no session to reconcile")
        turns = await self._root_turns(ref)
        if parts.turn_no == 1 and len(turns) == 1:
            return DispatchLookup(outcome="found", native_ref=str(turns[0]["id"]))
        return staged.turns.lookup_latest(
            record.idempotency_key, str(turns[-1]["id"]) if turns else None
        )

    async def _events(
        self, session: _AgentsSession, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        seen: set[str] = set()
        finalized: set[str] = set()
        stream = session.stream or self._client.stream_events(session_ref)

        async def retry_pending() -> None:
            if self._tools is not None:
                await self._tools.answer_pending(
                    session.operation, session.identity, session_ref, turn_ref
                )

        if self._tools is not None:
            stream = poll_while_idle(stream, retry_pending)
        session.active_stream = stream
        opened = session.opened
        session.stream, session.opened = None, None

        async def subscribed() -> AsyncIterator[SseEvent | StreamOpened]:
            if opened is not None:
                yield opened
            async for value in stream:
                yield value

        async for event in subscribed():
            if isinstance(event, StreamOpened):
                yield event
                state = await self._client.retrieve_session(session_ref)
                # A cursor from an item completion can use the provider's item pagination.
                item_after = (
                    after.removeprefix("item~") if after and after.startswith("item~") else None
                )
                async for item in self._client.items(
                    session_ref, turn_id=turn_ref, after=item_after
                ):
                    item_id = str(item["id"])
                    session.items[item_id] = item
                    if item.get("status") in {"completed", "failed", "incomplete"}:
                        finalized.add(item_id)
                        yield SseEvent(
                            event=frames.ITEM_DONE,
                            id=f"item~{item_id}",
                            data=json.dumps(
                                {
                                    "type": frames.ITEM_DONE,
                                    "turn_id": turn_ref,
                                    "item": item,
                                    "recovered": True,
                                }
                            ),
                        )
                if state.get("required_actions"):
                    yield SseEvent(
                        event="agent.session.requires_action",
                        data=json.dumps(
                            {"type": "agent.session.requires_action", "session": state}
                        ),
                    )
                    if self._tools is not None:
                        await self._tools.answer_pending(
                            session.operation, session.identity, session_ref, turn_ref
                        )
                # Retrieve the turn too: its terminal event may have preceded subscription.
                turn = await self._client.retrieve_turn(session_ref, turn_ref)
                if turn.get("status") in frames.TERMINAL:
                    yield SseEvent(
                        event=frames.PREFIX + "turn." + str(turn["status"]),
                        id="done",
                        data=json.dumps(
                            {
                                "type": frames.PREFIX + "turn." + str(turn["status"]),
                                "turn_id": turn_ref,
                                "turn": turn,
                            }
                        ),
                    )
                    return
                continue
            body = event.json()
            event_id = body.get("event_id") or event.id
            if event_id and str(event_id) in seen:
                continue
            if event_id:
                seen.add(str(event_id))
            kind = str(body.get("type") or event.event)
            if kind.startswith(frames.PREFIX + "turn.") and not frames.root_turn(body, turn_ref):
                continue
            item = frames.mapping(body.get("item"))
            item_id = str(body.get("item_id") or item.get("id") or "")
            if item_id in finalized:
                continue
            if kind == frames.ITEM_DONE and item_id:
                session.items[item_id] = item
                finalized.add(item_id)
                event_id = f"item~{item_id}"
            if kind in frames.TERMINAL_EVENTS:
                event_id = "done"
            yield SseEvent(event=kind, id=str(event_id) if event_id else None, data=event.data)
            if kind == "agent.session.requires_action" and self._tools is not None:
                await self._tools.answer_pending(
                    session.operation, session.identity, session_ref, turn_ref
                )

    async def _history_events(
        self, session: _AgentsSession, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        # Item IDs order creation, not completion. An earlier in-progress item can
        # finish after a later item was persisted, so every finite pass rescans the turn.
        # Stable completion provider keys let the frame store deduplicate prior results.
        del after
        scanned = 0
        async for item in self._client.items(session_ref, turn_id=turn_ref):
            scanned += 1
            if scanned > MAX_HISTORY_FRAMES:
                raise HistoryReplayIncomplete("native history frame bound")
            item_id = str(item["id"])
            session.items[item_id] = item
            if item.get("status") in {"completed", "failed", "incomplete"}:
                yield SseEvent(
                    event=frames.ITEM_DONE,
                    id=f"item~{item_id}",
                    data=json.dumps(
                        {
                            "type": frames.ITEM_DONE,
                            "turn_id": turn_ref,
                            "item": item,
                            "recovered": True,
                        }
                    ),
                )
        turn = await self._client.retrieve_turn(session_ref, turn_ref)
        if turn.get("status") in frames.TERMINAL:
            yield SseEvent(
                event=frames.PREFIX + "turn." + str(turn["status"]),
                id="done",
                data=json.dumps(
                    {
                        "type": frames.PREFIX + "turn." + str(turn["status"]),
                        "turn_id": turn_ref,
                        "turn": turn,
                    }
                ),
            )

    async def observe(self, request: ObserveRequest) -> AsyncIterator[LaneFrame]:
        session = self._session(request)
        try:
            async for frame in super().observe(request):
                yield frame
        finally:
            await self._close_stream(session)

    @staticmethod
    async def _close_stream(session: _AgentsSession) -> None:
        stream = session.active_stream or session.stream
        session.active_stream, session.stream, session.opened = None, None, None
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()

    def _classify(self, event: SseEvent, body: Mapping[str, Any]) -> Classified:
        kind = str(body.get("type") or event.event)
        if not kind:
            return Classified("skip")
        return Classified("terminal" if kind in frames.TERMINAL_EVENTS else "frame", kind)

    async def _read_turn(self, session_ref: str, turn_ref: str) -> Mapping[str, Any]:
        try:
            turn = await self._client.retrieve_turn(session_ref, turn_ref)
        except SessionNotFound as error:
            raise NativeTurnLost("the Agents API turn no longer exists") from error
        return {**turn, "turn": turn}

    def _final_key(self, turn_ref: str) -> str:
        return self.cursors.provider_key(turn_ref, "done")

    async def _on_terminal(self, session_ref: str, turn_ref: str, body: dict[str, Any]) -> None:
        # Full durable history produces final text even after recovery from a later item cursor.
        items = {
            str(item["id"]): item
            async for item in self._client.items(session_ref, turn_id=turn_ref)
        }
        await self._annotate_terminal(session_ref, turn_ref, body, items)

    async def _on_history_terminal(
        self, session_ref: str, turn_ref: str, body: dict[str, Any]
    ) -> None:
        items: dict[str, dict[str, Any]] = {}
        scanned = 0
        async for item in self._client.items(session_ref, turn_id=turn_ref):
            scanned += 1
            if scanned > MAX_HISTORY_FRAMES:
                raise HistoryReplayIncomplete("native terminal history frame bound")
            items[str(item["id"])] = item
        await self._annotate_terminal(session_ref, turn_ref, body, items)

    async def _annotate_terminal(
        self,
        session_ref: str,
        turn_ref: str,
        body: dict[str, Any],
        items: dict[str, dict[str, Any]],
    ) -> None:
        observed = frames.mapping(body.get("turn"))
        record = await self._client.retrieve_turn(session_ref, turn_ref)
        if (
            record.get("status") not in frames.TERMINAL
            and observed.get("status") in frames.TERMINAL
        ):
            record = observed
        session = self._by_ref(session_ref)
        if session is not None:
            items = {
                **{
                    key: item
                    for key, item in session.items.items()
                    if item.get("turn_id") == turn_ref
                },
                **items,
            }
        body["turn"] = record
        body["result"] = frames.final_text(items)
        if session is not None:
            session.items.update(items)
            session.records[turn_ref] = record

    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts:
        return frames.closing_facts(frames.mapping(frame.body))

    def _tool_call_ref(self, raw_kind: str, body: Mapping[str, Any]) -> str | None:
        item = frames.mapping(body.get("item"))
        call_id = body.get("call_id") or item.get("call_id")
        return str(call_id) if call_id else None

    async def status(self, request: StatusRequest) -> ProviderStatus:
        session = self._session(request)
        ref = request.session.native_session_ref or session.session_ref
        if ref is None:
            return ProviderStatus(status="not_started", terminal=False, idle=True)
        if request.turn and request.turn.native_turn_ref:
            record = await self._client.retrieve_turn(ref, request.turn.native_turn_ref)
            status = str(record.get("status") or "unknown")
            return ProviderStatus(
                status=status, terminal=status in frames.TERMINAL, idle=status in frames.TERMINAL
            )
        record = await self._client.retrieve_session(ref)
        return ProviderStatus(
            status=str(record.get("status") or "unknown"),
            terminal=False,
            idle=record.get("status") == "idle",
        )

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt:
        session = self._session(request)
        ref = request.turn.session.native_session_ref or session.session_ref
        turn = request.turn.native_turn_ref
        if ref is None or turn is None:
            return CancelReceipt(acknowledged=False, native_status="unknown")
        for _ in range(self._poll_limit):
            record = await self._client.retrieve_turn(ref, turn)
            if record.get("status") in frames.TERMINAL:
                return CancelReceipt(
                    acknowledged=True, already_terminal=True, native_status=str(record["status"])
                )
            try:
                await self._client.send_events(
                    ref,
                    [{"type": "agent.session.input.cancel"}],
                    idempotency_key=request.idempotency_key,
                )
                return CancelReceipt(acknowledged=True, native_status="accepted")
            except SessionBusy:
                await asyncio.sleep(self._poll_interval_s)
        return CancelReceipt(acknowledged=False, native_status="conflict")

    async def usage(self, request: UsageRequest) -> UsageReport:
        session = self._session(request)
        turn_id = request.turn.native_turn_ref if request.turn else None
        if session.session_ref is None or turn_id is None:
            return UsageReport(disposition="unknown")
        return frames.usage_report(await self._client.retrieve_turn(session.session_ref, turn_id))

    async def end_session(self, request: EndSessionRequest) -> CleanupReceipt:
        session = self._session(request)
        ref = request.session.native_session_ref or session.session_ref
        if ref is None:
            return CleanupReceipt(released=False)
        await self._close_stream(session)
        for turn in await self._root_turns(ref):
            if turn.get("status") in frames.TERMINAL:
                continue
            turn_handle = TurnHandle(
                session=request.session, turn_no=1, native_turn_ref=str(turn["id"])
            )
            cancelled = await self.cancel_turn(
                CancelTurnRequest(
                    **request.model_dump(exclude={"session", "reason"}),
                    turn=turn_handle,
                    reason=request.reason,
                )
            )
            if not cancelled.acknowledged:
                raise RemoteSessionError("could not cancel active Agents API turn before custody")
            for _ in range(self._poll_limit):
                terminal = await self._client.retrieve_turn(ref, str(turn["id"]))
                if terminal.get("status") in frames.TERMINAL:
                    break
                await asyncio.sleep(self._poll_interval_s)
            else:
                raise RemoteSessionError("Agents API turn still running after cancellation")
        # Custody precedes the retention deletion order; no destructive DELETE here.
        record = await self._client.retrieve_session(ref)
        manifest = {
            "session_id": ref,
            "status": record.get("status"),
            "turns": [turn async for turn in self._client.turns(ref)],
        }
        artifact = await self._artifacts.stage(
            request_scope=session.identity.request_scope,
            name=f"codex-agents/{request.harness_execution_id}/session-manifest.json",
            content=json.dumps(manifest, sort_keys=True).encode(),
            media_type="application/json",
        )
        await self._retention.after_custody(session.identity, ref)
        self._sessions.pop(request.harness_execution_id, None)
        return CleanupReceipt(released=True, artifact_refs=(artifact,))


def _input_message(text: str) -> dict[str, Any]:
    return {
        "type": "agent.session.input.message",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
    }


class AgentsSessionDeleter:
    def __init__(self, client: AgentsApiClient) -> None:
        self._client = client

    async def delete_session(self, session_ref: str) -> SessionDeletionOutcome:
        try:
            await self._client.delete_session(session_ref)
        except SessionNotFound:
            return "absent"
        # 409 raises SessionBusy; the durable retention workflow retries it.
        return "deleted"
