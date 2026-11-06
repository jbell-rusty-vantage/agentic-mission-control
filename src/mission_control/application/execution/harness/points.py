"""Cognition points of Session Lanes: the kernel port and the shared frame-boundary fold.

Cross-provider control (2026-11-05). Deep Agents writes one `mc.cognition_point.v1` row per
LangGraph root checkpoint of an attempt (`adapters/deep_agents/cognition_points.py`). Every
other lane runs through the `lane.turn` segment loop and has no checkpointer: its lifecycle
is the ordered Provider Frames it persisted (the Native Event Store, ADR-0028). This module
makes those frames the lane's coordinate: one point per *step boundary* of a turn (a model
message, a completed or failed tool call, a resolved approval, a compaction, a subagent end,
the turn end), keyed by the lane's native identity (`session_cursor`, `thread_item` or
`workspace_snapshot`) so the same index, reads, forks and transcript joins work on every
provider.

Two things live here:

- `PointCollectingLane`: the optional port a Session Lane implements to turn the persisted
  frames of one turn into `CognitionPointObservation`s. `LaneTurnService._settle` asks with
  `isinstance`, reads the attempt's frames through its frame reader, and hands the result to
  `settle_lane_session(points=...)`, which writes them in the settlement transaction beside
  the transition and result (`written_by: adapter`). A lane that does not implement the
  port writes no points, as before; nothing here settles anything (ADR-0007).
- `frame_boundary_points`: the pure fold every lane may reuse. It is deterministic over the
  persisted frames, so a reconciler re-deriving a settled generation (`TimeTravelLane.
  collect_points`) folds the same rows the settlement wrote.

Point identity: a step point's locator is the lane's native session and turn plus a step
reference. The default step reference is `<arrival_ordinal>:<kind>` of the step frame, which
is unique within one harness execution generation and stable once the frame is persisted; a
lane that has a native per-step identity (a Codex item id, a Managed Agents event id) passes
`point_for` and names it exactly instead.

One generation, several native turns (K1, 2026-11-05): a unit generation settles once, but
its harness execution may have run more than one native turn (an interrupted turn and its
`cancel_and_replace` replacement, a `missing_output` follow-up, a continuation turn). The
settlement folds every turn of the generation in arrival order (`generation_turns`) and
chains them (`fold_generation_points`): the first point of a later turn names the previous
turn's leaf as its `parent_locator`, only the last turn's leaf is the generation's `result`,
an interrupted turn's leaf carries `interrupted` and its replacement's first point
`replacement_start`. `TimeTravelLane.collect_points` re-derives a session lane's generation
with the same fold over the persisted frames (`namespace=<harness execution id>`,
`checkpointer_ref_digest=<generation>`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

from mission_control.domain.execution.cognition_points import (
    CognitionPointObservation,
    CognitionPointRef,
    PointRole,
    PointSource,
    SessionCursorPoint,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import ClosingFacts, NativeRefs
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame

# The frame kinds that close one observable step of a turn (a boundary a point stands at).
# Deltas, heartbeats, status and hook frames are folded into the next boundary's frame range.
STEP_KINDS: Final[frozenset[FrameKind]] = frozenset(
    {
        FrameKind.TURN_STARTED,
        FrameKind.MESSAGE,
        FrameKind.TOOL_CALL_COMPLETED,
        FrameKind.TOOL_CALL_FAILED,
        FrameKind.APPROVAL_RESOLVED,
        FrameKind.AFTER_COMPACTION,
        FrameKind.SUBAGENT_ENDED,
        FrameKind.TURN_ENDED,
        FrameKind.RUN_RESULT,
        FrameKind.ERROR,
    }
)
# A turn longer than this is folded to its first `MAX_STEP_POINTS - 1` boundaries plus the
# result; the result point then records `points_status: incomplete` (as Deep Agents does
# past `MAX_POINT_WALK`).
MAX_STEP_POINTS: Final = 512
MAX_STEP_REF_LENGTH: Final = 256
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnPointsRequest:
    """What `LaneTurnService._settle` hands a `PointCollectingLane` for one settled turn.

    `operation` is None when a reconciler re-derives a settled generation from its frames
    alone (`TimeTravelLane.collect_points`); a lane that needs the operation for its facts
    leaves them out in that case rather than failing the fold.
    """

    operation: OperationExecutionRequest | None
    lane_profile: str
    harness_execution_id: str
    generation: int
    native: NativeRefs
    turn_no: int
    frames: tuple[ProviderFrame, ...]
    facts: ClosingFacts
    attempt_ref: str | None = None
    # FT-F2: the native turn an `interrupt_and_inject` cancelled before this (replacement)
    # turn, when the lane knows it; its last point gets the `interrupted` role and this
    # turn's first point `replacement_start`.
    interrupted_turn_ref: str | None = None
    # The previous turn's (or the seed's) result point of the same unit, so the first point
    # of this turn names it as its parent outside the generation.
    source_point: CognitionPointRef | None = None
    # K1: this turn's leaf is the generation's `result` (False for an earlier turn of a
    # generation that ran several native turns), and this turn itself was cancelled by an
    # `interrupt_and_inject` and replaced (its leaf gets `interrupted`).
    terminal: bool = True
    interrupted: bool = False
    extras: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class PointCollectingLane(Protocol):
    """A Session Lane that folds its persisted frames into cognition points at settlement."""

    def turn_points(self, request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]: ...


def frames_of_turn(
    frames: Iterable[ProviderFrame], turn_ref: str | None
) -> tuple[ProviderFrame, ...]:
    """The frames of one native turn in arrival order (every frame when `turn_ref` is None)."""

    selected = [
        frame for frame in frames if turn_ref is None or frame.native_turn_ref in {None, turn_ref}
    ]
    selected.sort(key=lambda frame: frame.arrival_ordinal)
    return tuple(selected)


def default_step_ref(frame: ProviderFrame) -> str:
    """`<arrival_ordinal>:<kind>`: unique per execution generation, stable once persisted."""

    return f"{frame.arrival_ordinal}:{frame.kind.value}"[:MAX_STEP_REF_LENGTH]


def frame_boundary_points(
    frames: Sequence[ProviderFrame],
    *,
    session_ref: str,
    turn_ref: str,
    harness_execution_id: str | None = None,
    attempt_ref: str | None = None,
    point_for: Callable[[ProviderFrame], CognitionPointRef] | None = None,
    usage_of: Callable[[ProviderFrame], Mapping[str, int]] | None = None,
    facts_of: Callable[[ProviderFrame], Mapping[str, Any]] | None = None,
    step_kinds: frozenset[FrameKind] = STEP_KINDS,
    seedable: bool | Callable[[ProviderFrame], bool] = True,
    terminal: bool = True,
    source_point: CognitionPointRef | None = None,
    interrupted_turn_ref: str | None = None,
    interrupted_leaf: bool = False,
    is_input: Callable[[ProviderFrame], bool] | None = None,
    usage_kinds: frozenset[FrameKind] = frozenset({FrameKind.USAGE}),
    max_points: int = MAX_STEP_POINTS,
) -> tuple[CognitionPointObservation, ...]:
    """Fold one turn's persisted frames into points, oldest first, one per step boundary.

    Every step frame (a kind in `step_kinds`) becomes a point whose `frame_keys` are the
    provider keys of the frames since the previous boundary, itself included; trailing
    frames after the last boundary (a usage frame after `turn_ended`) belong to the last
    point. Roles: the first point is `input` when its frame is `turn_started` (else
    `intermediate`); the last point is `leaf`, and `result` too when `terminal`; a point
    whose frame is a model message or tool close is `intermediate`. `source` is `input` for
    the first boundary, `compaction` after a compaction, `interrupt` at an error, else
    `loop`. `usage_delta` is the sum of `usage_of` over the usage frames of the range;
    `message_count` the running count of `message` frames. `parent_locator` chains the
    points; the first point names `source_point` as its parent outside the generation.
    `facts_of` adds lane-specific redacted facts to `channel_facts`. `interrupted_leaf`
    marks the last point `interrupted` (the turn an `interrupt_and_inject` cancelled).
    `is_input` (KR2) says whether the first boundary frame is the turn's input for a lane
    whose turns open with no `turn_started` frame (a hosted lane's opening user message);
    the default is `frame.kind is FrameKind.TURN_STARTED`. `usage_kinds` are the frame kinds
    `usage_of` is read on (`usage` by default; a lane whose turn end carries the counts and
    writes no usage frame passes `turn_ended` too).
    """

    ordered = frames_of_turn(frames, turn_ref)
    if not ordered:
        return ()
    boundaries = [frame for frame in ordered if frame.kind in step_kinds]
    if not boundaries:
        # No boundary frame at all (a lane that writes a single `run_result`): the turn's
        # last frame is its one point, so the settlement still names a result point.
        boundaries = [ordered[-1]]
    truncated = False
    if len(boundaries) > max_points:
        boundaries = [*boundaries[: max_points - 1], boundaries[-1]]
        truncated = True
    boundary_ids = {id(frame) for frame in boundaries}
    observations: list[CognitionPointObservation] = []
    pending_keys: list[str] = []
    pending_usage: dict[str, int] = {}
    messages = 0
    previous_locator: str | None = None
    index = 0
    last_boundary = boundaries[-1]
    for frame in ordered:
        pending_keys.append(frame.provider_key)
        if frame.kind in usage_kinds and usage_of is not None:
            for key, amount in usage_of(frame).items():
                pending_usage[key] = pending_usage.get(key, 0) + int(amount)
        if frame.kind is FrameKind.MESSAGE:
            messages += 1
        if id(frame) not in boundary_ids:
            continue
        is_first = index == 0
        is_last = frame is last_boundary
        roles: list[PointRole] = []
        opens_turn = (
            is_input(frame) if is_input is not None else frame.kind is FrameKind.TURN_STARTED
        )
        if is_first and opens_turn:
            roles.append("input")
        if is_last:
            roles.append("leaf")
            if terminal:
                roles.append("result")
            if interrupted_leaf:
                roles.append("interrupted")
        elif "input" not in roles:
            roles.append("intermediate")
        if is_first and interrupted_turn_ref is not None:
            roles.append("replacement_start")
        source: PointSource
        if is_first:
            source = "input"
        elif frame.kind is FrameKind.AFTER_COMPACTION:
            source = "compaction"
        elif frame.kind is FrameKind.ERROR:
            source = "interrupt"
        else:
            source = "loop"
        point = (
            point_for(frame)
            if point_for is not None
            else _default_point(frame, session_ref=session_ref, turn_ref=turn_ref)
        )
        facts: dict[str, Any] = {
            "frame_kind": frame.kind.value,
            "raw_kind": frame.raw_kind,
            "arrival_ordinal": frame.arrival_ordinal,
        }
        if frame.tool_call_ref is not None:
            facts["tool_call_ref"] = frame.tool_call_ref
        if frame.subordinate_ref is not None:
            facts["subordinate_ref"] = frame.subordinate_ref
        if facts_of is not None:
            facts.update(dict(facts_of(frame)))
        if is_last and truncated:
            facts["points_status"] = "incomplete"
            facts["points_walked"] = len(boundaries)
        is_seedable = seedable(frame) if callable(seedable) else seedable
        observations.append(
            CognitionPointObservation(
                point=point,
                parent_locator=previous_locator,
                parent_point=source_point if is_first else None,
                ordinal=index,
                source=source,
                roles=tuple(roles),
                attempt_ref=attempt_ref,
                harness_execution_id=harness_execution_id,
                native_turn_ref=turn_ref,
                frame_keys=tuple(pending_keys[-4_096:]),
                message_count=messages,
                channel_facts=facts,
                usage_delta=dict(pending_usage),
                seedable=is_seedable,
                native_observed_at=frame.provider_timestamp or frame.observed_at,
            )
        )
        previous_locator = point.locator
        pending_keys = []
        pending_usage = {}
        index += 1
    if pending_keys and observations:
        # Trailing frames (usage, status) after the last boundary belong to the result.
        last = observations[-1]
        observations[-1] = last.model_copy(
            update={
                "frame_keys": (*last.frame_keys, *pending_keys)[-4_096:],
                "usage_delta": _merged(last.usage_delta, pending_usage),
            }
        )
    return tuple(observations)


def _default_point(frame: ProviderFrame, *, session_ref: str, turn_ref: str) -> CognitionPointRef:
    return SessionCursorPoint(
        session_ref=session_ref[:512], turn_ref=turn_ref[:512], step_ref=default_step_ref(frame)
    )


def _merged(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    merged = dict(left)
    for key, amount in right.items():
        merged[key] = merged.get(key, 0) + int(amount)
    return merged


# --- One generation, several native turns (K1) --------------------------------------------


def generation_turns(
    frames: Iterable[ProviderFrame],
) -> tuple[tuple[str, tuple[ProviderFrame, ...]], ...]:
    """The native turns of one harness execution generation, in first-arrival order, each
    with its frames. A frame that names no turn (a lifecycle frame the lane wrote itself, a
    hook frame) belongs to the turn in progress when it arrived; frames before any turn
    belong to the first turn. Frames of a generation that named no turn at all make one
    turn keyed by the empty string (the caller supplies the native turn ref it settles)."""

    ordered = sorted(frames, key=lambda frame: frame.arrival_ordinal)
    turns: dict[str, list[ProviderFrame]] = {}
    current: str | None = None
    orphans: list[ProviderFrame] = []
    for frame in ordered:
        ref = frame.native_turn_ref
        if ref is not None:
            if ref not in turns:
                turns[ref] = []
                if current is None and orphans:
                    turns[ref].extend(orphans)
                    orphans = []
            current = ref
            turns[ref].append(frame)
        elif current is None:
            orphans.append(frame)
        else:
            turns[current].append(frame)
    if not turns and orphans:
        turns[""] = orphans
    return tuple((ref, tuple(items)) for ref, items in turns.items())


def fold_generation_points(
    frames: Sequence[ProviderFrame],
    *,
    collect: Callable[[TurnPointsRequest], tuple[CognitionPointObservation, ...]],
    lane_profile: str,
    harness_execution_id: str,
    generation: int,
    session_ref: str | None,
    facts: ClosingFacts,
    operation: OperationExecutionRequest | None = None,
    attempt_ref: str | None = None,
    last_turn_no: int = 1,
    last_turn_ref: str | None = None,
    replaced: Mapping[str, str] | None = None,
    source_point: CognitionPointRef | None = None,
) -> tuple[CognitionPointObservation, ...]:
    """Fold every native turn of one generation through `collect` and chain the turns.

    `replaced` maps a replacement turn's native ref to the turn it replaced (the kernel
    reads it from the dispatch journal, `<execution>:<generation>:replace:<turn>`): the
    replaced turn's leaf carries `interrupted`, the replacement's first point
    `replacement_start`. `last_turn_no` is the settled turn's number; earlier turns count
    down from it. Only the last turn (the one named by `last_turn_ref`, else the last by
    arrival) is `terminal`. A locator observed twice across turns (an adapter defect) keeps
    its first observation; the duplicate is dropped and logged, never the settlement.
    """

    turns = list(generation_turns(frames))
    if not turns:
        return ()
    if last_turn_ref is not None and any(ref == last_turn_ref for ref, _ in turns):
        # The settled turn is the generation's last, whatever its arrival position.
        turns.sort(key=lambda item: item[0] == last_turn_ref)
    replaced = dict(replaced or {})
    interrupted_refs = set(replaced.values())
    observations: list[CognitionPointObservation] = []
    seen: set[str] = set()
    previous_leaf: str | None = None
    for index, (turn_ref, turn_frames) in enumerate(turns):
        last = index == len(turns) - 1
        ref = turn_ref or last_turn_ref or f"turn:{index + 1}"
        request = TurnPointsRequest(
            operation=operation,
            lane_profile=lane_profile,
            harness_execution_id=harness_execution_id,
            generation=generation,
            native=NativeRefs(session_ref=session_ref, turn_ref=ref),
            turn_no=max(1, last_turn_no - (len(turns) - 1 - index)),
            frames=turn_frames,
            facts=facts,
            attempt_ref=attempt_ref,
            interrupted_turn_ref=replaced.get(turn_ref),
            source_point=source_point if index == 0 else None,
            terminal=last,
            interrupted=turn_ref in interrupted_refs,
        )
        points = list(collect(request))
        if not points:
            continue
        if index > 0 and previous_leaf is not None:
            points[0] = points[0].model_copy(
                update={"parent_locator": previous_leaf, "parent_point": None}
            )
        kept: list[CognitionPointObservation] = []
        for point in points:
            if point.locator in seen:
                _LOGGER.warning(
                    "cognition point %s observed twice in generation %s of %s; kept the first",
                    point.locator,
                    generation,
                    harness_execution_id,
                )
                continue
            seen.add(point.locator)
            kept.append(point)
        if not kept:
            continue
        leaf = next((item for item in reversed(kept) if "leaf" in item.roles), None)
        previous_leaf = leaf.locator if leaf is not None else kept[-1].locator
        observations.extend(kept)
    return tuple(observations)


__all__ = [
    "MAX_STEP_POINTS",
    "STEP_KINDS",
    "PointCollectingLane",
    "TurnPointsRequest",
    "default_step_ref",
    "fold_generation_points",
    "frame_boundary_points",
    "frames_of_turn",
    "generation_turns",
]
