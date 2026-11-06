"""Cognition points of the hosted session lanes (cross-provider control, 2026-11-05).

A Remote Session Lane has no checkpointer: its lifecycle is the ordered Provider Frames it
persisted for one native turn (ADR-0028). `hosted_turn_points` is the one fold both hosted
lanes (`claude_managed`, `codex_agents`) run at settlement (`PointCollectingLane.turn_points`)
and again when the reconciler re-derives a settled generation (`TimeTravelLane.
collect_points`): the kernel's `frame_boundary_points` over the turn's frames, keyed by the
lane's native step identity, plus the two hosted corrections the kernel fold cannot know:

- the hosted APIs write no `turn_started` frame: the turn opens with the user message the
  lane sent (a Managed `user.message` event, an Agents `message:user` item), so the first
  boundary that *is* that message gets the `input` role the Deep Agents input checkpoint has;
- a lane whose usage is reported on the terminal record rather than on usage frames (the
  Agents API `turn.usage`) puts that usage on the result point's `usage_delta`.

Each lane supplies `HostedPointRules`: how a frame names its native step (`point_for`), what
a usage frame adds (`usage_of`, stateful when the provider reports cumulative figures), the
redacted facts a point keeps (`facts_of`), whether a frame is the turn's opening user message
(`is_input`) and the usage a terminal body carries (`terminal_usage`). Everything here is
pure over persisted frames; nothing settles anything (ADR-0007).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mission_control.application.execution.harness.points import (
    TurnPointsRequest,
    frame_boundary_points,
    frames_of_turn,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointObservation,
    CognitionPointRef,
    PointRole,
)
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import ProviderFrame

MAX_FACT_TEXT = 256


def frame_body(frame: ProviderFrame) -> dict[str, Any]:
    """The frame's complete (already redacted) body, or `{}` when it was excerpted."""

    return frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)


def bounded_text(value: Any, limit: int = MAX_FACT_TEXT) -> str | None:
    if value is None or value == "":
        return None
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return text[:limit]


@dataclass(frozen=True)
class HostedPointRules:
    """What one hosted lane knows about its frames (see the module doc)."""

    point_for: Callable[[ProviderFrame, str, str], CognitionPointRef]
    """`(frame, session_ref, turn_ref)` -> the native point the step frame stands at."""

    usage_of: Callable[[], Callable[[ProviderFrame], Mapping[str, int]]] | None = None
    """A fresh (possibly stateful) usage reader per fold; None when the lane writes no
    `usage` frames."""

    facts_of: Callable[[ProviderFrame], Mapping[str, Any]] | None = None
    is_input: Callable[[ProviderFrame], bool] | None = None
    """Whether a boundary frame is the turn's opening user message."""

    terminal_usage: Callable[[ProviderFrame], Mapping[str, int]] | None = None
    """The usage a terminal frame's body reports for the whole turn (Agents `turn.usage`)."""

    step_usage_of: Callable[[ProviderFrame], Mapping[str, int]] | None = None
    """The usage a non-`usage` frame carries for its own model request (a Managed
    `span.model_request_end`), summed over every frame of a point's range."""


def hosted_turn_points(
    frames: Sequence[ProviderFrame],
    rules: HostedPointRules,
    *,
    session_ref: str,
    turn_ref: str,
    harness_execution_id: str | None = None,
    attempt_ref: str | None = None,
    terminal: bool = True,
    source_point: CognitionPointRef | None = None,
    interrupted_turn_ref: str | None = None,
) -> tuple[CognitionPointObservation, ...]:
    """One turn's persisted frames folded into points, oldest first (see the module doc)."""

    ordered = frames_of_turn(frames, turn_ref)
    if not ordered:
        return ()
    usage_of = rules.usage_of() if rules.usage_of is not None else None

    def point_for(frame: ProviderFrame) -> CognitionPointRef:
        return rules.point_for(frame, session_ref, turn_ref)

    def facts_of(frame: ProviderFrame) -> Mapping[str, Any]:
        facts: dict[str, Any] = {"provider_key": frame.provider_key}
        if rules.facts_of is not None:
            facts.update(dict(rules.facts_of(frame)))
        return facts

    observations = list(
        frame_boundary_points(
            ordered,
            session_ref=session_ref,
            turn_ref=turn_ref,
            harness_execution_id=harness_execution_id,
            attempt_ref=attempt_ref,
            point_for=point_for,
            usage_of=usage_of,
            facts_of=facts_of,
            terminal=terminal,
            source_point=source_point,
            interrupted_turn_ref=interrupted_turn_ref,
        )
    )
    if not observations:
        return ()
    by_key = {frame.provider_key: frame for frame in ordered}
    first = observations[0]
    first_frame = by_key.get(str(first.channel_facts.get("provider_key")))
    if (
        first_frame is not None
        and rules.is_input is not None
        and rules.is_input(first_frame)
        and "input" not in first.roles
    ):
        roles: list[PointRole] = [
            "input",
            *(role for role in first.roles if role != "intermediate"),
        ]
        observations[0] = first.model_copy(update={"roles": tuple(roles)})
    if rules.step_usage_of is not None:
        for index, observation in enumerate(observations):
            added: dict[str, int] = {}
            for key in observation.frame_keys:
                frame = by_key.get(key)
                if frame is None:
                    continue
                for name, amount in rules.step_usage_of(frame).items():
                    added[name] = added.get(name, 0) + int(amount)
            if added:
                merged_step = dict(observation.usage_delta)
                for name, amount in added.items():
                    merged_step[name] = merged_step.get(name, 0) + amount
                observations[index] = observation.model_copy(update={"usage_delta": merged_step})
    if rules.terminal_usage is not None:
        last = observations[-1]
        last_frame = by_key.get(str(last.channel_facts.get("provider_key")))
        if last_frame is not None and "result" in last.roles:
            reported = dict(rules.terminal_usage(last_frame))
            if reported:
                merged = dict(last.usage_delta)
                for key, amount in reported.items():
                    merged[key] = merged.get(key, 0) + int(amount)
                observations[-1] = last.model_copy(update={"usage_delta": merged})
    return tuple(observations)


def turn_points_for(
    request: TurnPointsRequest, rules: HostedPointRules
) -> tuple[CognitionPointObservation, ...]:
    """`PointCollectingLane.turn_points` for a hosted lane: the fold over the settlement's
    request. Without native refs there is no coordinate and no point."""

    session_ref = request.native.session_ref
    turn_ref = request.native.turn_ref
    if session_ref is None or turn_ref is None:
        return ()
    return hosted_turn_points(
        request.frames,
        rules,
        session_ref=session_ref,
        turn_ref=turn_ref,
        harness_execution_id=request.harness_execution_id,
        attempt_ref=request.attempt_ref,
        terminal=request.facts.terminal,
        source_point=request.source_point,
        interrupted_turn_ref=request.interrupted_turn_ref,
    )


def generation_points(
    frames: Sequence[ProviderFrame],
    rules: HostedPointRules,
    *,
    session_ref: str | None = None,
    source_point: CognitionPointRef | None = None,
) -> tuple[CognitionPointObservation, ...]:
    """Every turn of one execution generation folded in arrival order, each turn's first
    point naming the previous turn's result as its parent outside the turn (the reconciler's
    re-derivation; `TimeTravelLane.collect_points`)."""

    ordered = sorted(frames, key=lambda frame: frame.arrival_ordinal)
    turns: list[str] = []
    for frame in ordered:
        if frame.native_turn_ref is not None and frame.native_turn_ref not in turns:
            turns.append(frame.native_turn_ref)
    points: list[CognitionPointObservation] = []
    previous = source_point
    for turn_ref in turns:
        turn_frames = [frame for frame in ordered if frame.native_turn_ref == turn_ref]
        ref = session_ref or turn_frames[0].native_session_ref
        folded = hosted_turn_points(
            turn_frames,
            rules,
            session_ref=ref,
            turn_ref=turn_ref,
            harness_execution_id=str(turn_frames[0].harness_execution_id),
            source_point=previous,
        )
        if folded:
            points.extend(folded)
            previous = folded[-1].point
    return tuple(points)


__all__ = [
    "MAX_FACT_TEXT",
    "HostedPointRules",
    "bounded_text",
    "frame_body",
    "generation_points",
    "hosted_turn_points",
    "turn_points_for",
]
