"""Cursor cognition points: one `session_cursor` point per step of a run, plus the turn-close
`workspace_snapshot` (cross-provider control, 2026-11-05).

The Cursor lane has no checkpointer. Its lifecycle is the ordered Provider Frames the bridge
(`cursor_local`, keyed `bridge:<run>:<offset>`) or the Cloud Agents SSE stream (`cursor_cloud`,
keyed `sse:<run>:<event id>`) persisted. `cursor_turn_points` folds one native run's frames
with the kernel's `frame_boundary_points` into points keyed by the SDK agent id (session),
the run id (turn) and the lane's native per-step identity (the bridge offset, the SSE event
id); a synthetic frame (the lane's own `agent.created`/`send.accepted` lifecycle frames, the
`run.final` the lane writes after `410 stream_expired`) keeps the kernel's default
`<arrival_ordinal>:<kind>` reference.

At turn close the lane freezes the workspace (`mc.cursor_snapshot.v1` named
`cursor-snapshot:<ref>` on local; `branch:<branch>@<sha>` on cloud). The settlement runs
after `end_session`, so the last turn's points name that snapshot: every step point carries
`channel_facts.turn_snapshot_ref` (the files a `read_as_of` lists are the turn-close state,
not the step's), the result point carries it as `workspace_checkpoint_ref`, and one
`workspace_snapshot` point joins the turn (`session_ref`, `turn_ref`) as the coordinate a
fork restores from (R2). Facts are small and redacted: tool names, statuses and call ids,
message roles, token counts; never message text (the frames hold it).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from mission_control.adapters.cursor.frames import first, offset_of
from mission_control.adapters.cursor.snapshot import SNAPSHOT_REF_PREFIX
from mission_control.adapters.cursor.usage import cursor_token_usage
from mission_control.application.execution.harness.points import (
    TurnPointsRequest,
    frame_boundary_points,
)
from mission_control.application.workspaces.snapshots import BRANCH_SNAPSHOT_REF_PREFIX
from mission_control.domain.execution.cognition_points import (
    CognitionPointObservation,
    CognitionPointRef,
    SessionCursorPoint,
    WorkspaceSnapshotPoint,
)
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame

LOCAL_PROFILE: Final = "cursor_local"
CLOUD_PROFILE: Final = "cursor_cloud"
# The `channel_facts` key every step point of a closed turn carries (the turn-close snapshot).
TURN_SNAPSHOT_FACT: Final = "turn_snapshot_ref"
_SSE_PREFIX: Final = "sse:"
_FACT_TEXT: Final = 128


def local_step_ref(frame: ProviderFrame) -> str | None:
    """The bridge offset of a persisted `cursor_local` frame (None for a synthetic one)."""

    return offset_of(frame.provider_key)


def cloud_step_ref(frame: ProviderFrame) -> str | None:
    """The SSE event id of a persisted `cursor_cloud` frame (`sse:<run>:<id>`); None for the
    synthetic `run.final` or `usage` frames."""

    key = frame.provider_key
    if not key.startswith(_SSE_PREFIX):
        return None
    _run, separator, event_id = key.removeprefix(_SSE_PREFIX).rpartition(":")
    return event_id if separator and event_id else None


def step_ref_of(profile: str, frame: ProviderFrame) -> str | None:
    return cloud_step_ref(frame) if profile == CLOUD_PROFILE else local_step_ref(frame)


def frame_body(frame: ProviderFrame) -> dict[str, Any]:
    """The persisted body of a frame (whole when the excerpt holds it; else the lifecycle
    fields alone)."""

    return frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)


def usage_of(frame: ProviderFrame) -> Mapping[str, int]:
    """Token counts a `usage` (or turn-ended) frame reports, in the kernel's `usage_delta`
    dimensions; nothing when the provider reported no attributable counts."""

    body = frame_body(frame)
    raw = body.get("usage")
    if not isinstance(raw, Mapping):
        return {}
    report = cursor_token_usage(raw)
    if report.disposition == "unknown":
        return {}
    delta = {
        "tokens.input": report.input_tokens,
        "tokens.output": report.output_tokens,
        "tokens.total": report.total_tokens,
    }
    if report.cache_read_tokens is not None:
        delta["tokens.cache_read"] = report.cache_read_tokens
    if report.cache_write_tokens is not None:
        delta["tokens.cache_write"] = report.cache_write_tokens
    return delta


def usage_frame_kinds(frames: Iterable[ProviderFrame]) -> frozenset[FrameKind]:
    """The frame kinds a turn's token counts are read from: the SDK's `usage` message
    (local) repeats the turn-ended counts, so a turn that has one is charged from it alone;
    a turn without one (cloud, a local run that ended early) from its turn-ended frame. The
    `RunResult` body repeats the counts too and is never charged."""

    if any(frame.kind is FrameKind.USAGE for frame in frames):
        return frozenset({FrameKind.USAGE})
    return frozenset({FrameKind.USAGE, FrameKind.TURN_ENDED})


def _bounded(value: Any) -> str | None:
    return str(value)[:_FACT_TEXT] if value not in (None, "") else None


def facts_of(frame: ProviderFrame) -> dict[str, Any]:
    """Redacted, bounded facts of one step frame: what happened, never what was said."""

    body = frame_body(frame)
    facts: dict[str, Any] = {"provider_key": frame.provider_key[:512]}
    kind = frame.kind
    if kind in {FrameKind.TOOL_CALL_COMPLETED, FrameKind.TOOL_CALL_FAILED}:
        facts["tool_name"] = _bounded(first(body, "name", "tool_name", "toolName"))
        facts["tool_status"] = _bounded(first(body, "status"))
    elif kind is FrameKind.MESSAGE:
        message = body.get("message")
        role = first(message, "role") if isinstance(message, Mapping) else first(body, "role")
        facts["message_role"] = _bounded(role) or frame.raw_kind[:64]
    elif kind in {FrameKind.RUN_RESULT, FrameKind.ERROR}:
        facts["native_status"] = _bounded(first(body, "status"))
        model = body.get("model")
        if isinstance(model, Mapping) and first(model, "id"):
            facts["model"] = _bounded(first(model, "id"))
    elif kind is FrameKind.APPROVAL_RESOLVED:
        facts["approval"] = _bounded(first(body, "decision", "result"))
    return {key: value for key, value in facts.items() if value is not None}


def snapshot_ref_of(request: TurnPointsRequest, closed: Mapping[str, str] | None) -> str | None:
    """The turn-close snapshot: what `end_session` recorded for this execution (the harness's
    memo, both profiles), else the `cursor-snapshot:` / `branch:` ref among the closing
    facts' output refs (the local lease's snapshot is an output ref)."""

    if closed is not None and closed.get("snapshot_ref"):
        return closed["snapshot_ref"]
    for ref in request.facts.output_refs:
        if ref.startswith((SNAPSHOT_REF_PREFIX, BRANCH_SNAPSHOT_REF_PREFIX)):
            return ref
    return None


def cursor_turn_points(
    request: TurnPointsRequest, *, closed: Mapping[str, str] | None = None
) -> tuple[CognitionPointObservation, ...]:
    """`PointCollectingLane.turn_points` for both Cursor profiles.

    `closed` is what the harness's `end_session` recorded for the execution (the snapshot
    ref, the repository, the branch and head on cloud); it names the turn's workspace point
    only when the request is `terminal` (the generation's settled turn is the one the
    session closed on).
    """

    frames = request.frames
    session_ref = request.native.session_ref or next(
        (frame.native_session_ref for frame in frames), None
    )
    turn_ref = request.native.turn_ref or next(
        (frame.native_turn_ref for frame in frames if frame.native_turn_ref), None
    )
    if not frames or session_ref is None or turn_ref is None:
        return ()
    profile = request.lane_profile
    snapshot_ref = snapshot_ref_of(request, closed) if request.terminal else None
    cloud_facts = (
        {
            key: closed[key]
            for key in ("repository", "branch", "head")
            if closed is not None and closed.get(key)
        }
        if profile == CLOUD_PROFILE
        else {}
    )

    def point_for(frame: ProviderFrame) -> CognitionPointRef:
        step = step_ref_of(profile, frame) or f"{frame.arrival_ordinal}:{frame.kind.value}"
        return SessionCursorPoint(
            session_ref=str(session_ref)[:512], turn_ref=str(turn_ref)[:512], step_ref=step[:256]
        )

    def step_facts(frame: ProviderFrame) -> Mapping[str, Any]:
        facts = facts_of(frame)
        if snapshot_ref is not None:
            facts[TURN_SNAPSHOT_FACT] = snapshot_ref
        facts.update(cloud_facts)
        return facts

    usage_kinds = usage_frame_kinds(frames)
    points = list(
        frame_boundary_points(
            frames,
            session_ref=str(session_ref),
            turn_ref=str(turn_ref),
            harness_execution_id=request.harness_execution_id,
            attempt_ref=request.attempt_ref,
            point_for=point_for,
            usage_of=usage_of,
            usage_kinds=usage_kinds,
            facts_of=step_facts,
            # Every step is a fork head: the transcript to the step is reconstructed from
            # the frames, the workspace restored from the turn-close snapshot (R2) or not
            # at all (R1); the seed receipt says which.
            seedable=True,
            terminal=request.terminal,
            source_point=request.source_point,
            interrupted_turn_ref=request.interrupted_turn_ref,
            interrupted_leaf=request.interrupted,
        )
    )
    if not points or snapshot_ref is None:
        return tuple(points)
    result = points[-1].model_copy(update={"workspace_checkpoint_ref": snapshot_ref[:1024]})
    points[-1] = result
    points.append(
        CognitionPointObservation(
            point=WorkspaceSnapshotPoint(
                snapshot_ref=snapshot_ref[:1024],
                session_ref=str(session_ref)[:512],
                turn_ref=str(turn_ref)[:512],
            ),
            parent_locator=result.locator,
            parent_point=result.point,
            ordinal=len(points),
            source="loop",
            roles=(),
            attempt_ref=request.attempt_ref,
            harness_execution_id=request.harness_execution_id,
            native_turn_ref=str(turn_ref),
            message_count=result.message_count,
            channel_facts={
                "frame_kind": "workspace_snapshot",
                "snapshot_kind": (
                    "branch"
                    if snapshot_ref.startswith(BRANCH_SNAPSHOT_REF_PREFIX)
                    else "cursor_snapshot"
                ),
                "closes_turn": str(turn_ref)[:512],
                "closes_step": result.locator,
                **cloud_facts,
            },
            usage_delta={},
            seedable=True,
            native_observed_at=result.native_observed_at,
        )
    )
    return tuple(points)


__all__ = [
    "CLOUD_PROFILE",
    "LOCAL_PROFILE",
    "TURN_SNAPSHOT_FACT",
    "cloud_step_ref",
    "cursor_turn_points",
    "facts_of",
    "frame_body",
    "local_step_ref",
    "snapshot_ref_of",
    "step_ref_of",
    "usage_frame_kinds",
    "usage_of",
]
