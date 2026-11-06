"""Fact derivation from closing frames, and the projector that applies them (SPEC-03, C2).

`derive(frames, context)` is pure and deterministic: it reads only closing frames of the
execution's current generation, in arrival order, and returns typed `FrameFact`s
following the SPEC-03 lifecycle synthesis table:

Closing frame -> fact -> mission event:

- first closing frame of a native session -> session started -> `session.started`
  (plus `activation.phase_changed{executing}` on Cursor lanes);
- first closing frame of a turn -> turn n opened -> `session.turn_started`;
- `tool_call_completed` / `tool_call_failed` -> tool effect settled or failed, deduplicated
  by `tool_call_ref` -> `tool_call.completed{status}`;
- `hook_result{decision: deny}` naming a tool call -> effect denied before claim ->
  `tool_call.completed{status: denied}`;
- `session_state{requires_action | awaiting_human ...}` -> approval requested ->
  `activation.phase_changed{awaiting_human}`; `approval_resolved` -> `{executing}`;
- `after_compaction` -> compaction observed -> `session.compaction_observed`;
- `usage` within a turn, then `turn_ended` -> turn n closed with usage dispositions ->
  `session.turn_completed`; a `usage` after the turn closed (Cursor `charged_cents`) ->
  `session.usage_settled`;
- `run_result` -> execution outcome per workflow-types/05 section 3.5 ->
  `attempt.completed` (or `activation.phase_changed{follow_up_turn}`), and `session.ended`;
- `error{unknown_state: true}` -> unit in doubt (existing reconciliation path) ->
  `activation.lifecycle_changed{waiting, blocker: in_doubt}`;
- `subagent_ended` (closing; 1.4.4 TR-G5) -> subordinate started and ended, both from the
  closing frame since `subagent_started` is not closing, deduplicated by (child ref, tool
  call) -> `subordinate.started`, `subordinate.ended` (ADR-0040).

Turn ordinals come from closing frames alone, so lanes without native turn ids (Cursor)
and lanes with them (Deep Agents invocations) derive identically. Deltas, starts, status
and heartbeats never reach this module. `FrameFactProjector` reads a harness execution's
closing frames, derives, and applies the facts not yet applied through the run-control
reducer's `apply_frame_facts` action (idempotent by the run's frame-fact cursor).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from mission_control.application.frames.lineage import folds_subordinate_usage, usage_body
from mission_control.application.frames.sink import FrameReader
from mission_control.application.frames.streams import deep_agents_after_point_ref
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import (
    CLOSING_KINDS,
    FrameKind,
    HarnessExecutionHandle,
    LaneProfile,
    ProviderFrame,
)
from mission_control.domain.frames.facts import (
    ApprovalRequestedFact,
    ApprovalResolvedFact,
    AttemptOutcome,
    CompactionObservedFact,
    ExecutionOutcomeFact,
    FailureClass,
    FrameFact,
    MissingOutputPolicy,
    SessionEndedFact,
    SessionStartedFact,
    SubordinateEndedFact,
    SubordinateStartedFact,
    ToolEffectFact,
    TurnCompletedFact,
    TurnStartedFact,
    UnitInDoubtFact,
    UsageSettledFact,
)
from mission_control.domain.frames.usage import usage_report
from mission_control.domain.policies.contracts import (
    MAX_FRAME_FACTS_PER_ACTION,
    ActorContext,
    ApplyFrameFactsAction,
    CommandResult,
    CommandStatus,
    LifecycleCommand,
    RunProjection,
)

logger = logging.getLogger(__name__)

DIGEST_PREFIX = "sha256:"
AWAITING_STATES = frozenset(
    {
        "requires_action",
        "awaiting_human",
        "awaiting_approval",
        "waiting_on_approval",
        "waiting_on_user_input",
    }
)
CAPACITY_CODES = frozenset(
    {"agent_busy", "409", "429", "rate_limited", "session_token_limit_reached"}
)
_FINISHED = frozenset({"finished", "completed", "succeeded", "success", "end_turn"})
_FAILED = frozenset({"error", "failed", "failure"})
_EXPIRED = frozenset({"expired", "timeout", "timed_out"})
_CANCELLED = frozenset({"cancelled", "canceled", "interrupted", "aborted"})
_TURN_NEUTRAL = frozenset({FrameKind.RUN_RESULT, FrameKind.ERROR})


@dataclass(frozen=True)
class CompletionEvidence:
    """The Completion Candidate the attempt registered (workflow-types/05 section 3.4)."""

    declared_outputs: frozenset[str] = frozenset()
    registered_outputs: frozenset[str] = frozenset()

    @property
    def covers_declared_outputs(self) -> bool:
        return self.declared_outputs <= self.registered_outputs


CompletionPolicy = Literal["candidate_required", "deferred"]


@dataclass(frozen=True)
class DeriveContext:
    """What derivation needs beyond the frames.

    `completion_policy = "deferred"` leaves a provider `finished` without an attempt outcome
    because another authority (the Deep Agents operation settlement) decides it; errors,
    expiry and cancellation still map per section 3.5.

    `replaced_turn_refs` names the native turns an applied `interrupt_and_inject` cancelled
    and replaced (`cancel_and_replace`, ADR-0032): such a turn's cancelled `run_result` is the
    inject's replacement boundary, not the attempt's outcome, which comes from a later turn.
    """

    lane: LaneProfile
    current_generation: int
    completion: CompletionEvidence | None = None
    completion_policy: CompletionPolicy = "candidate_required"
    missing_output_policy: MissingOutputPolicy = "follow_up_turn"
    cancel_command_admitted: bool = False
    replaced_turn_refs: frozenset[str] = frozenset()


def _digest(value: Any) -> str | None:
    return (
        value
        if isinstance(value, str) and value.startswith(DIGEST_PREFIX) and len(value) == 71
        else None
    )


def _status(body: Mapping[str, Any]) -> str:
    for key in ("status", "outcome", "result"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value.lower()
    return "unknown"


def _error_code(body: Mapping[str, Any]) -> str:
    for key in ("error_code", "code", "error_type", "terminal_reason"):
        value = body.get(key)
        if isinstance(value, str | int) and str(value):
            return str(value).lower()
    return ""


def _claude_result(body: Mapping[str, Any]) -> tuple[str, str]:
    """`ResultMessage`: `subtype` and `is_error` decide; `result` is the final text."""

    subtype = str(body.get("subtype") or "").lower()
    reason = str(body.get("terminal_reason") or "").lower()
    api_status = body.get("api_error_status")
    code = str(api_status) if isinstance(api_status, int) else (reason or subtype)
    if reason in {"aborted_tools", "aborted_streaming"}:
        return "cancelled", code
    if reason in _CANCELLED:
        return reason, code
    if subtype == "success" and body.get("is_error") is not True:
        return "success", ""
    if subtype.startswith("error") or body.get("is_error") is True:
        return "failed", code
    return subtype or "unknown", code


def _codex_result(body: Mapping[str, Any]) -> tuple[str, str]:
    """App-server `turn/completed{turn:{status,error}}` or exec `turn.completed|failed`."""

    if body.get("type") == "turn.completed":
        return "completed", ""
    if body.get("type") == "turn.failed":
        return "failed", ""
    turn = body.get("turn")
    if not isinstance(turn, Mapping):
        return "unknown", ""
    error = turn.get("error")
    code = ""
    if isinstance(error, Mapping):
        code = _error_code(error)
    return str(turn.get("status") or "unknown").lower(), code


def provider_result(lane: LaneProfile, body: Mapping[str, Any]) -> tuple[str, str]:
    """(provider status, error code) of a `run_result` body under the lane's native shape."""

    if lane == LaneProfile.CLAUDE_AGENT_SDK:
        return _claude_result(body)
    if lane == LaneProfile.CODEX:
        return _codex_result(body)
    return _status(body), _error_code(body)


def map_execution_outcome(
    provider_status: str,
    *,
    error_code: str,
    context: DeriveContext,
) -> tuple[AttemptOutcome | None, FailureClass | None, bool, MissingOutputPolicy | None]:
    """workflow-types/05 section 3.5: (outcome, failure class, missing outputs, policy).

    Returns outcome None for a `finished` whose outputs are not covered under
    `follow_up_turn` (or whose completion is deferred) and for an unknown status.
    """

    status = provider_status.lower()
    if status in _FINISHED:
        if context.completion_policy == "deferred":
            return None, None, False, None
        covered = context.completion is not None and context.completion.covers_declared_outputs
        if covered:
            return AttemptOutcome.SUCCEEDED, None, False, None
        if context.missing_output_policy == "not_accepted":
            return AttemptOutcome.FAILED, FailureClass.OUTPUTS_MISSING, True, "not_accepted"
        return None, None, True, "follow_up_turn"
    if status in _EXPIRED:
        return AttemptOutcome.FAILED, FailureClass.TIMEOUT, False, None
    if status in _CANCELLED:
        if context.cancel_command_admitted:
            return AttemptOutcome.CANCELLED, FailureClass.CANCELLED_BY_COMMAND, False, None
        return AttemptOutcome.FAILED, FailureClass.PROVIDER_ERROR, False, None
    if status in _FAILED or status in CAPACITY_CODES:
        if error_code in CAPACITY_CODES or status in CAPACITY_CODES:
            return AttemptOutcome.FAILED, FailureClass.CAPACITY, False, None
        return AttemptOutcome.FAILED, FailureClass.PROVIDER_ERROR, False, None
    return None, None, False, None


@dataclass
class _ExecutionState:
    sessions: set[str] = field(default_factory=set)
    open_turn: int | None = None
    closed_turns: int = 0
    closed_turn_refs: set[tuple[str, str | None]] = field(default_factory=set)
    turn_ordinals: dict[tuple[str, str | None], int] = field(default_factory=dict)
    turn_usage: list[tuple[ProviderFrame, Mapping[str, Any]]] = field(default_factory=list)
    settled_tools: set[str] = field(default_factory=set)
    run_results: set[tuple[str, str | None]] = field(default_factory=set)
    compactions: set[tuple[str, str | None, str, str]] = field(default_factory=set)
    subordinates: set[tuple[str | None, str | None]] = field(default_factory=set)


# A provider subagent's own lifecycle never moves its parent: these kinds from a frame with
# `subordinate_ref` are lineage evidence only (multi-provider SPEC-04).
_PARENT_LIFECYCLE_KINDS = frozenset({FrameKind.TURN_ENDED, FrameKind.RUN_RESULT})


def _evidence(frame: ProviderFrame) -> dict[str, Any]:
    return {
        "frame_id": str(frame.frame_id),
        "arrival_ordinal": frame.arrival_ordinal,
        "harness_execution_id": str(frame.harness_execution_id),
        "generation": frame.generation,
        "native_session_ref": frame.native_session_ref,
        "native_turn_ref": frame.native_turn_ref,
        "subordinate_ref": frame.subordinate_ref,
        "observed_at": frame.observed_at,
    }


def _tool_ref(frame: ProviderFrame, body: Mapping[str, Any]) -> str | None:
    if frame.tool_call_ref:
        return frame.tool_call_ref
    for key in ("tool_call_id", "callId", "call_id", "tool_use_id"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _exit_code(body: Mapping[str, Any]) -> int | None:
    for key in ("exit_code", "exitCode"):
        value = body.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def derive(frames: Sequence[ProviderFrame], context: DeriveContext) -> tuple[FrameFact, ...]:
    """Typed facts from closing frames only; deterministic for the same input."""

    closing = sorted(
        (
            frame
            for frame in frames
            if frame.closing
            and frame.kind in CLOSING_KINDS
            and frame.generation == context.current_generation
        ),
        key=lambda frame: (str(frame.harness_execution_id), frame.arrival_ordinal),
    )
    folds_children = folds_subordinate_usage(context.lane)
    states: dict[UUID, _ExecutionState] = {}
    facts: list[FrameFact] = []
    for frame in closing:
        state = states.setdefault(frame.harness_execution_id, _ExecutionState())
        body = frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)
        evidence = _evidence(frame)
        child = frame.subordinate_ref is not None
        if child and (
            frame.kind in _PARENT_LIFECYCLE_KINDS
            or (frame.kind == FrameKind.USAGE and not folds_children)
        ):
            continue
        parent_evidence = {**evidence, "subordinate_ref": None}
        turn_ref = (frame.native_session_ref, frame.native_turn_ref)
        closed_turn = frame.native_turn_ref is not None and turn_ref in state.closed_turn_refs
        if frame.native_session_ref not in state.sessions and not (child and state.sessions):
            state.sessions.add(frame.native_session_ref)
            facts.append(SessionStartedFact(**parent_evidence, lane_profile=context.lane))
        if frame.kind == FrameKind.TURN_ENDED and frame.native_turn_ref is not None and closed_turn:
            continue
        if closed_turn and frame.kind in (FrameKind.SESSION_STATE, FrameKind.APPROVAL_RESOLVED):
            # Retain delayed approval observations in the frame store, but they cannot
            # move a completed turn back into awaiting_human or executing.
            continue
        if frame.kind in (FrameKind.TOOL_CALL_COMPLETED, FrameKind.TOOL_CALL_FAILED):
            ref = _tool_ref(frame, body)
            if ref is None or ref in state.settled_tools:
                # A resent or reordered settlement is not new activity: no turn opens for it.
                continue
        if frame.kind == FrameKind.USAGE and (
            closed_turn
            or (frame.native_turn_ref is None and state.open_turn is None and state.closed_turns)
        ):
            facts.append(
                UsageSettledFact(
                    **evidence,
                    turn_ordinal=state.turn_ordinals.get(turn_ref, state.closed_turns),
                    usage=usage_report(
                        context.lane, [(str(frame.frame_id), usage_body(context.lane, body))]
                    ),
                )
            )
            continue
        # A child's activity is inside its parent's turn: it may open the first parent turn,
        # never reopen one the parent already closed.
        opens_turn = not closed_turn and (not child or state.closed_turns == 0)
        if opens_turn and frame.kind not in _TURN_NEUTRAL and state.open_turn is None:
            state.open_turn = state.closed_turns + 1
            state.turn_ordinals[turn_ref] = state.open_turn
            facts.append(TurnStartedFact(**parent_evidence, turn_ordinal=state.open_turn))
        turn = state.turn_ordinals.get(turn_ref, state.open_turn or max(state.closed_turns, 1))
        if frame.kind == FrameKind.USAGE:
            state.turn_usage.append((frame, usage_body(context.lane, body)))
        elif frame.kind in (FrameKind.TOOL_CALL_COMPLETED, FrameKind.TOOL_CALL_FAILED):
            ref = _tool_ref(frame, body)
            if ref is None or ref in state.settled_tools:
                continue
            state.settled_tools.add(ref)
            name = body.get("name")
            facts.append(
                ToolEffectFact(
                    **evidence,
                    turn_ordinal=turn,
                    tool_call_ref=ref,
                    name=name if isinstance(name, str) else None,
                    status=(
                        "completed" if frame.kind == FrameKind.TOOL_CALL_COMPLETED else "failed"
                    ),
                    args_digest=_digest(body.get("args_digest")),
                    result_digest=_digest(body.get("result_digest")) or frame.body_digest,
                    exit_code=_exit_code(body),
                )
            )
        elif frame.kind == FrameKind.HOOK_RESULT:
            decision = str(body.get("decision") or body.get("permission") or "").lower()
            ref = _tool_ref(frame, body)
            if decision == "deny" and ref is not None and ref not in state.settled_tools:
                state.settled_tools.add(ref)
                name = body.get("tool_name") or body.get("name")
                facts.append(
                    ToolEffectFact(
                        **evidence,
                        turn_ordinal=turn,
                        tool_call_ref=ref,
                        name=name if isinstance(name, str) else None,
                        status="denied",
                        args_digest=_digest(body.get("input_digest")),
                        result_digest=frame.body_digest,
                    )
                )
        elif frame.kind == FrameKind.SESSION_STATE:
            state_name = str(body.get("state") or body.get("status") or "").lower()
            if state_name in AWAITING_STATES:
                request = body.get("request_id") or body.get("request_ref")
                facts.append(
                    ApprovalRequestedFact(**evidence, request_ref=str(request) if request else None)
                )
        elif frame.kind == FrameKind.APPROVAL_RESOLVED:
            request = body.get("request_id") or body.get("request_ref")
            resolution = body.get("decision")
            facts.append(
                ApprovalResolvedFact(
                    **evidence,
                    request_ref=str(request) if request else None,
                    decision=str(resolution) if resolution else None,
                )
            )
        elif frame.kind == FrameKind.AFTER_COMPACTION:
            summary_digest = _digest(body.get("summary_digest")) or frame.body_digest
            # One compaction may be observed twice (B4's middleware custom event and the
            # `_summarization_event` state update): one fact per (session, cutoff, summary).
            compaction = (
                frame.native_session_ref,
                frame.subordinate_ref,
                str(body.get("cutoff_index")),
                summary_digest,
            )
            if compaction in state.compactions:
                continue
            state.compactions.add(compaction)
            facts.append(CompactionObservedFact(**evidence, summary_digest=summary_digest))
        elif frame.kind == FrameKind.TURN_ENDED:
            if frame.native_turn_ref is not None:
                state.closed_turn_refs.add(turn_ref)
                state.turn_ordinals[turn_ref] = turn
            bodies = state.turn_usage or [(frame, usage_body(context.lane, body))]
            report = usage_report(
                context.lane, [(str(item.frame_id), data) for item, data in bodies]
            )
            stop = body.get("stop_reason")
            summary = body.get("result_summary_ref")
            facts.append(
                TurnCompletedFact(
                    **evidence,
                    turn_ordinal=turn,
                    usage=report,
                    usage_frame_ids=tuple(str(item.frame_id) for item, _data in state.turn_usage),
                    stop_reason=str(stop) if stop else None,
                    result_summary_ref=str(summary) if summary else None,
                )
            )
            state.closed_turns = turn
            state.open_turn = None
            state.turn_usage = []
        elif frame.kind == FrameKind.RUN_RESULT:
            if turn_ref in state.run_results:
                continue
            provider_status, error_code = provider_result(context.lane, body)
            if (
                provider_status in _CANCELLED
                and frame.native_turn_ref is not None
                and frame.native_turn_ref in context.replaced_turn_refs
            ):
                # cancel_and_replace: the interrupted turn ended for the replacement turn; the
                # attempt continues there and settles from its (or a later) terminal result.
                state.run_results.add(turn_ref)
                continue
            known_terminal = provider_status in (
                _FINISHED | _FAILED | _EXPIRED | _CANCELLED | CAPACITY_CODES
            )
            if known_terminal:
                # One terminal outcome per native turn; an unknown observation cannot
                # suppress a later authoritative result during reconciliation.
                state.run_results.add(turn_ref)
            outcome, failure, missing, policy = map_execution_outcome(
                provider_status, error_code=error_code, context=context
            )
            if outcome is not None or missing:
                facts.append(
                    ExecutionOutcomeFact(
                        **evidence,
                        provider_status=provider_status,
                        outcome=outcome,
                        failure_class=failure,
                        missing_outputs=missing,
                        missing_output_policy=policy,
                    )
                )
            elif provider_status not in _FINISHED:
                # A status the 05 section 3.5 table does not name: never guessed, in doubt.
                facts.append(UnitInDoubtFact(**evidence, reason=f"run_result:{provider_status}"))
            if known_terminal and (
                context.lane == LaneProfile.DEEP_AGENTS or body.get("session_ended") is True
            ):
                facts.append(SessionEndedFact(**evidence))
        elif frame.kind == FrameKind.ERROR:
            if body.get("unknown_state") is True:
                reason = body.get("reason") or body.get("error_type")
                facts.append(UnitInDoubtFact(**evidence, reason=str(reason) if reason else None))
        elif frame.kind == FrameKind.SUBAGENT_ENDED:
            child_ref = _subordinate_ref(frame, body)
            tool_ref = _tool_ref(frame, body)
            if child_ref is None and tool_ref is None:
                continue  # nothing stable identifies the child (ADR-0040: refs, never text)
            if (child_ref, tool_ref) in state.subordinates:
                continue
            state.subordinates.add((child_ref, tool_ref))
            child_evidence = {**evidence, "subordinate_ref": child_ref}
            name = body.get("name") or body.get("subagent") or body.get("child_name")
            status = body.get("status")
            started_ref = body.get("started_frame_ref") or body.get("started_native_event_ref")
            started = str(started_ref) if started_ref else None
            facts.append(
                SubordinateStartedFact(
                    **child_evidence,
                    tool_call_ref=tool_ref,
                    name=name if isinstance(name, str) else None,
                    started_frame_ref=started,
                )
            )
            facts.append(
                SubordinateEndedFact(
                    **child_evidence,
                    tool_call_ref=tool_ref,
                    name=name if isinstance(name, str) else None,
                    status=str(status) if status else None,
                    result_digest=_digest(body.get("result_digest")) or frame.body_digest,
                    started_frame_ref=started,
                )
            )
    return tuple(facts)


def _subordinate_ref(frame: ProviderFrame, body: Mapping[str, Any]) -> str | None:
    """The child's stable ref: the frame's `subordinate_ref`, else what the closing body
    names (`subordinate_ref`, `child_ref`, the child's checkpoint namespace)."""

    if frame.subordinate_ref:
        return frame.subordinate_ref
    for key in ("subordinate_ref", "child_ref", "checkpoint_ns", "namespace"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


# --- Projector ------------------------------------------------------------------------------


class FrameFactRunControl(Protocol):
    async def execute(self, command: LifecycleCommand) -> CommandResult: ...

    async def get_run(self, request_scope: str, run_id: str) -> RunProjection: ...


def checkpoint_point_refs(frames: Sequence[ProviderFrame]) -> dict[str, dict[str, object]]:
    """1.4.4 (TR-D7): the cognition point a closing frame carries, by frame id. Deep Agents
    `turn_ended` and `run_result` bodies name the turn's result checkpoint
    (`result_checkpoint_id`, `adapters/deep_agents/frames.py`); the thread is the body's
    `thread_id` or the frame's native session. A root checkpoint has the empty namespace."""

    refs: dict[str, dict[str, object]] = {}
    for frame in frames:
        if not frame.closing:
            continue
        if frame.kind in (FrameKind.TURN_ENDED, FrameKind.RUN_RESULT):
            body = frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)
            checkpoint_id = body.get("result_checkpoint_id")
            if isinstance(checkpoint_id, str) and checkpoint_id:
                thread = body.get("thread_id")
                refs[str(frame.frame_id)] = {
                    "kind": "checkpoint",
                    "thread_id": (
                        thread if isinstance(thread, str) and thread else frame.native_session_ref
                    ),
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_id,
                    "relation": "result",
                }
                continue
        # Every other closing frame (a tool result, a hook result, usage): the point it
        # followed, which the Deep Agents recorder keys every frame by (P4.2 `after_point_ref`).
        after = deep_agents_after_point_ref(frame)
        if after is not None:
            refs[str(frame.frame_id)] = {**after, "relation": "after"}
    return refs


@dataclass(frozen=True)
class FrameFactTarget:
    """The harness execution whose closing frames are projected into run state.

    `unit_key` (1.4.4, TR-D7) is the runtime unit the execution belongs to: the activation
    row's `activation_key`, which `record_attempt` writes from the unit key. The caller that
    holds the execution binding resolves it; None leaves the derived events' `unit_key`
    unset.
    """

    request_scope: str
    run_key: str
    harness_execution_id: UUID
    activation_id: UUID
    attempt_no: int
    lane: LaneProfile
    unit_key: str | None = None

    @classmethod
    def from_handle(
        cls, handle: HarnessExecutionHandle, *, run_key: str, unit_key: str | None = None
    ) -> FrameFactTarget:
        return cls(
            request_scope=handle.request_scope,
            run_key=run_key,
            harness_execution_id=handle.harness_execution_id,
            activation_id=handle.activation_id,
            attempt_no=handle.attempt_no,
            lane=handle.lane_profile,
            unit_key=unit_key,
        )


@dataclass(frozen=True)
class FrameFactProjection:
    generation: int | None
    derived: int
    applied: int
    through_ordinal: int
    rejected_reason: str | None = None


class FrameFactsRejected(RuntimeError):
    def __init__(self, reason_code: str, reason: str) -> None:
        super().__init__(reason)
        self.reason_code = reason_code


def _batches(facts: Sequence[FrameFact], size: int) -> list[list[FrameFact]]:
    """Batches that never split the facts of one frame (the cursor is per ordinal)."""

    batches: list[list[FrameFact]] = []
    current: list[FrameFact] = []
    index = 0
    while index < len(facts):
        ordinal = facts[index].arrival_ordinal
        group = []
        while index < len(facts) and facts[index].arrival_ordinal == ordinal:
            group.append(facts[index])
            index += 1
        if current and len(current) + len(group) > size:
            batches.append(current)
            current = []
        current.extend(group)
    if current:
        batches.append(current)
    return batches


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FrameFactProjector:
    """Derive facts from an execution's closing frames and apply the unapplied ones.

    ``max_frames`` bounds each read page, not the execution's retained history. Derivation
    needs preceding turns to attribute late observations and must never truncate silently.
    """

    def __init__(
        self,
        frames: FrameReader,
        run_control: FrameFactRunControl,
        *,
        actor: ActorContext,
        idempotency_issuer: str = "mission-control-frame-facts",
        clock: Callable[[], datetime] = _utc_now,
        batch_size: int = 64,
        max_frames: int = 10_000,
    ) -> None:
        if not 1 <= batch_size <= MAX_FRAME_FACTS_PER_ACTION:
            raise ValueError("frame fact batch size is out of bounds")
        if max_frames < 1:
            raise ValueError("frame read page size must be positive")
        self._frames = frames
        self._run_control = run_control
        self._actor = actor
        self._issuer = idempotency_issuer
        self._clock = clock
        self._batch_size = batch_size
        self._max_frames = max_frames

    async def project(
        self,
        target: FrameFactTarget,
        *,
        completion: CompletionEvidence | None = None,
        completion_policy: CompletionPolicy = "candidate_required",
        missing_output_policy: MissingOutputPolicy = "follow_up_turn",
        cancel_command_admitted: bool = False,
        replaced_turn_refs: frozenset[str] = frozenset(),
    ) -> FrameFactProjection:
        generation = await self._frames.current_generation(
            target.request_scope, target.harness_execution_id
        )
        if generation is None:
            return FrameFactProjection(generation=None, derived=0, applied=0, through_ordinal=0)
        closing: list[ProviderFrame] = []
        after = 0
        while True:
            page = await self._frames.frames_for_execution(
                target.request_scope,
                target.harness_execution_id,
                generation,
                after_ordinal=after,
                closing_only=True,
                limit=self._max_frames,
            )
            if not page:
                break
            closing.extend(page)
            after = page[-1].arrival_ordinal
            if len(page) < self._max_frames:
                break
        context = DeriveContext(
            lane=target.lane,
            current_generation=generation,
            completion=completion,
            completion_policy=completion_policy,
            missing_output_policy=missing_output_policy,
            cancel_command_admitted=cancel_command_admitted,
            replaced_turn_refs=replaced_turn_refs,
        )
        facts = derive(closing, context)
        point_refs = checkpoint_point_refs(closing)
        applied = 0
        through = 0
        contention = 0
        while contention < 16:
            run = await self._run_control.get_run(target.request_scope, target.run_key)
            cursor = next(
                (
                    item.through_ordinal
                    for item in run.frame_fact_cursors
                    if item.harness_execution_id == str(target.harness_execution_id)
                    and item.generation == generation
                ),
                0,
            )
            through = max(through, cursor)
            pending = [fact for fact in facts if fact.arrival_ordinal > cursor]
            if not pending:
                return FrameFactProjection(generation, len(facts), applied, through)
            batch = _batches(pending, self._batch_size)[0]
            last = batch[-1].arrival_ordinal
            # The cursor covers every closing frame up to the last fact's frame; trailing
            # closing frames that produced no fact are covered when the batch is the last.
            covered = max(last, closing[-1].arrival_ordinal) if len(batch) == len(pending) else last
            command = LifecycleCommand(
                command_id=(
                    f"frame-facts:{target.harness_execution_id}:{generation}:{covered}"
                    f":v{run.version}"
                ),
                idempotency_issuer=self._issuer,
                request_scope=target.request_scope,
                run_id=target.run_key,
                expected_run_version=run.version,
                actor=self._actor,
                action=ApplyFrameFactsAction(
                    harness_execution_id=str(target.harness_execution_id),
                    generation=generation,
                    lane_profile=target.lane.value,
                    activation_id=str(target.activation_id),
                    attempt_no=target.attempt_no,
                    through_ordinal=covered,
                    facts=tuple(batch),
                    unit_key=target.unit_key,
                    point_refs=(
                        {
                            fact.frame_id: point_refs[fact.frame_id]
                            for fact in batch
                            if fact.frame_id in point_refs
                        }
                        or None
                    ),
                ),
                reason="derive mission state from closing provider frames",
                evidence_refs=tuple(dict.fromkeys(fact.native_event_ref for fact in batch))[:64],
                occurred_at=self._clock(),
                correlation_id=f"frames:{target.harness_execution_id}:{generation}",
            )
            result = await self._run_control.execute(command)
            if result.status == CommandStatus.ACCEPTED:
                applied += len(batch)
                through = covered
                contention = 0
                continue
            if result.status == CommandStatus.STALE or result.reason_code in {
                "stale_run_version",
                "frame_facts_already_applied",
            }:
                contention += 1
                continue
            return FrameFactProjection(
                generation, len(facts), applied, through, rejected_reason=result.reason_code
            )
        raise FrameFactsRejected(
            "frame_facts_contended", "frame facts stayed stale after repeated retries"
        )
