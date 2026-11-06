"""Cursor time travel: `read_as_of` (R2), `seed_fork` (R2) and `collect_points` over the
persisted frames and the turn-close workspace snapshots (cross-provider control, 2026-11-05).

Cursor keeps no forkable conversation: the SDK's `Agent` has no fork, the Cloud Agents API no
session copy. What the lane *does* have is the Native Event Store (every bridge / SSE event
of every run, redacted at write) and the snapshot it froze when the turn closed
(`mc.cursor_snapshot.v1` on local, `branch:<branch>@<sha>` on cloud). So:

- `read_as_of` reconstructs the transcript from the frames of the point's turn up to the
  point's frame (model messages, tool calls with their arguments digest, tool results, the
  final text; `history = reconstructed`) and lists the files of the turn-close snapshot
  (the manifest's paths, sizes and digests on local; the branch tree at the recorded head
  on cloud, when a branch reader is composed). The files are the state at the *turn's*
  close, named so in `withheld` for an intermediate point; `restore_level` is `R2` when
  files were listed, `R1` when only the transcript was.
- `seed_fork` creates what the derived unit's first session needs and nothing in the
  source: the turn-close snapshot ref (restored into a fresh lease by `prepare`, or the
  branch head a new cloud agent starts on) and a reconstructed transcript prompt staged as
  an artifact (`transcript_ref`), which `start`/`send_turn` prefix to the derived unit's
  first instruction (the hydration turn), plus the injected message as its last line. The
  receipt's derived point is the `workspace_snapshot` coordinate of the derived run; the
  copy is idempotent per `(fork_request_id, derived_unit_key)` in this process and
  content-addressed in the payload store.
- `collect_points` re-folds one generation's frames with the settlement's fold
  (`fold_generation_points` + `cursor_turn_points`), so the reconciler writes the rows the
  settlement would have (without the turn-close snapshot, which frames do not carry).

Reads and seeds need the caller's request scope (frames and snapshots are tenant-scoped
rows): the lane is a `ScopedTimeTravelLane`; the registry binds it per call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

from mission_control.adapters.cursor import snapshot as snapshots
from mission_control.adapters.cursor.cognition_points import (
    CLOUD_PROFILE,
    LOCAL_PROFILE,
    TURN_SNAPSHOT_FACT,
    cursor_turn_points,
    frame_body,
    usage_frame_kinds,
    usage_of,
)
from mission_control.adapters.cursor.frames import first
from mission_control.adapters.cursor.snapshot import SNAPSHOT_ROOTS
from mission_control.adapters.remote_session.custody import parse_branch_snapshot
from mission_control.application.execution.harness.points import fold_generation_points
from mission_control.application.execution.harness.time_travel import (
    SEED_HEAD_MESSAGE_COUNT,
    ForkSeedReceipt,
    ForkSeedRequest,
    TimeTravelUnsupported,
)
from mission_control.application.frames.sink import FrameReader
from mission_control.domain.execution.cognition_points import (
    CognitionCoordinate,
    CognitionPointObservation,
    CognitionPointRecord,
    GraphStateAsOf,
    SessionCursorPoint,
    StateAsOf,
    StateFile,
    StateMessage,
    ToolCallFact,
    WorkspaceSnapshotPoint,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.execution.lanes import RestoreLevel
from mission_control.domain.frames.contracts import (
    DEFAULT_EXCERPT_CAP_BYTES,
    FrameKind,
    ProviderFrame,
)

# `native_artifacts` keys of a Cursor seed receipt (what `prepare`/`start` read back).
SEED_SNAPSHOT_REF: Final = "snapshot_ref"
SEED_TRANSCRIPT_REF: Final = "transcript_ref"
SEED_SOURCE_SESSION: Final = "source_session_ref"
SEED_SOURCE_TURN: Final = "source_turn_ref"
SEED_SOURCE_STEP: Final = "source_step_ref"
SEED_HEAD: Final = "seed_head"
HYDRATION_HEADER: Final = "# Continuation of a Cursor session (Mission Control fork)"
_PAGE: Final = 10_000
_MAX_PAGES: Final = 100


class BranchTreeReader(Protocol):
    """What the cloud read needs of the SCM: the files under roots at a commit."""

    async def read_tree(
        self, *, repository: str, ref: str, roots: Sequence[str]
    ) -> list[tuple[str, bytes]]: ...


SnapshotStoreResolver = Callable[[str], snapshots.SnapshotArtifacts | None]


@dataclass
class _Transcript:
    """The reconstructed state up to a point: messages, usage and what was withheld."""

    messages: list[StateMessage] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    withheld: list[str] = field(default_factory=list)
    pending_text: list[str] = field(default_factory=list)


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bounded_message(
    role: str,
    text: str | None,
    cap: int,
    *,
    message_id: str | None = None,
    name: str | None = None,
    tool_call_id: str | None = None,
    tool_calls: tuple[ToolCallFact, ...] = (),
) -> StateMessage:
    raw = text or ""
    encoded = raw.encode("utf-8")
    truncated = len(encoded) > cap
    shown = encoded[:cap].decode("utf-8", errors="ignore") if truncated else raw
    return StateMessage(
        id=message_id,
        role=role[:32],
        name=name[:256] if name else None,
        tool_call_id=tool_call_id,
        tool_calls=tool_calls,
        text=shown if raw else None,
        text_bytes=len(encoded),
        text_digest=_digest(raw) if raw else None,
        truncated=truncated,
    )


def _message_text(body: Mapping[str, Any]) -> str:
    """The text of a local `assistant`/`user` SDK message or a cloud `assistant` event."""

    message = body.get("message")
    content: Any = message.get("content") if isinstance(message, Mapping) else None
    if content is None:
        content = first(body, "text", "content")
    if isinstance(content, str):
        return content
    if isinstance(content, Iterable):
        parts = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _message_role(body: Mapping[str, Any], raw_kind: str) -> str:
    message = body.get("message")
    role = first(message, "role") if isinstance(message, Mapping) else first(body, "role")
    if isinstance(role, str) and role:
        return role
    return "user" if raw_kind == "user" else "assistant"


def _tool_fact(body: Mapping[str, Any], frame: ProviderFrame) -> ToolCallFact:
    arguments = body.get("args")
    if not isinstance(arguments, Mapping):
        arguments = body.get("arguments") if isinstance(body.get("arguments"), Mapping) else None
    serialized = json.dumps(arguments, sort_keys=True, default=str) if arguments else ""
    return ToolCallFact(
        id=frame.tool_call_ref or first(body, "callId", "call_id"),
        name=str(first(body, "name", "tool_name", "toolName") or "tool")[:256],
        arguments=dict(arguments) if arguments and len(serialized) <= 2_048 else None,
        arguments_digest=_digest(serialized) if serialized else None,
        arguments_bytes=len(serialized.encode("utf-8")),
        truncated=bool(arguments) and len(serialized) > 2_048,
    )


def reconstruct_transcript(frames: Sequence[ProviderFrame], *, cap: int) -> _Transcript:
    """Fold the frames of one run, oldest first, into the messages a reader expects."""

    state = _Transcript()
    ordered = sorted(frames, key=lambda item: item.arrival_ordinal)
    charged = usage_frame_kinds(ordered)

    def flush() -> None:
        if state.pending_text:
            state.messages.append(_bounded_message("assistant", "".join(state.pending_text), cap))
            state.pending_text = []

    for frame in ordered:
        body = frame_body(frame)
        if not body and frame.body_bytes:
            state.withheld.append(f"frame {frame.provider_key}: body beyond the excerpt cap")
        kind = frame.kind
        if kind is FrameKind.MESSAGE_DELTA:
            text = _message_text(body)
            if text:
                state.pending_text.append(text)
        elif kind is FrameKind.MESSAGE:
            flush()
            state.messages.append(
                _bounded_message(
                    _message_role(body, frame.raw_kind),
                    _message_text(body),
                    cap,
                    message_id=frame.provider_key,
                )
            )
        elif kind is FrameKind.TOOL_CALL_STARTED:
            flush()
            state.messages.append(
                _bounded_message(
                    "assistant",
                    None,
                    cap,
                    message_id=frame.provider_key,
                    tool_calls=(_tool_fact(body, frame),),
                )
            )
        elif kind in {FrameKind.TOOL_CALL_COMPLETED, FrameKind.TOOL_CALL_FAILED}:
            flush()
            result = body.get("result") if "result" in body else body.get("error")
            tool_text: str | None = (
                result
                if isinstance(result, str)
                else json.dumps(result, sort_keys=True, default=str)
                if result is not None
                else None
            )
            state.messages.append(
                _bounded_message(
                    "tool",
                    tool_text,
                    cap,
                    message_id=frame.provider_key,
                    name=str(first(body, "name", "tool_name", "toolName") or "tool"),
                    tool_call_id=frame.tool_call_ref or first(body, "callId", "call_id"),
                )
            )
        elif kind in {FrameKind.RUN_RESULT, FrameKind.ERROR}:
            flush()
            text = first(body, "result", "text")
            if (
                isinstance(text, str)
                and text
                and not (state.messages and state.messages[-1].text == text)
            ):
                state.messages.append(
                    _bounded_message("assistant", text, cap, message_id=frame.provider_key)
                )
        if frame.kind in charged:
            for key, amount in usage_of(frame).items():
                state.usage[key] = state.usage.get(key, 0) + int(amount)
    flush()
    return state


def render_hydration_prompt(
    transcript: _Transcript,
    *,
    source_session: str,
    source_turn: str,
    source_locator: str,
    restore_level: RestoreLevel,
    snapshot_ref: str | None,
    message: str | None,
) -> str:
    """The hydration turn's text: what the source agent said and did up to the point."""

    lines = [
        HYDRATION_HEADER,
        "",
        f"Source: agent `{source_session}`, run `{source_turn}`, point `{source_locator}`.",
        (
            f"Workspace: restored at {restore_level} from `{snapshot_ref}` (the files as the "
            "source turn closed)."
            if snapshot_ref
            else f"Workspace: not restored ({restore_level}); start from the packet."
        ),
        "",
        "The transcript below is what the previous agent said and did up to that point.",
        "Continue the work from there; do not repeat finished steps.",
        "",
    ]
    for item in transcript.messages:
        if item.tool_calls:
            for call in item.tool_calls:
                arguments = (
                    json.dumps(call.arguments, sort_keys=True)
                    if call.arguments is not None
                    else f"<arguments {call.arguments_digest}>"
                )
                lines.append(f"[assistant -> tool {call.name} ({call.id or '-'})] {arguments}")
        elif item.role == "tool":
            lines.append(
                f"[tool {item.name or 'tool'} ({item.tool_call_id or '-'})] {item.text or ''}"
            )
        else:
            lines.append(f"[{item.role}] {item.text or ''}")
        if item.truncated:
            lines.append("  (truncated)")
    if transcript.withheld:
        lines.append("")
        lines.append(
            f"({len(transcript.withheld)} frame bodies beyond the excerpt cap were omitted)"
        )
    if message:
        lines.extend(["", f"[operator] {message}"])
    return "\n".join(lines) + "\n"


class CursorTimeTravel:
    """`TimeTravelLane` + `ScopedTimeTravelLane` for one Cursor profile."""

    def __init__(
        self,
        profile: str,
        frames: FrameReader,
        *,
        snapshots: snapshots.SnapshotArtifacts | SnapshotStoreResolver | None = None,
        branches: BranchTreeReader | None = None,
        request_scope: str | None = None,
        excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
        clock: Callable[[], datetime] | None = None,
        seeded: dict[tuple[str, str], ForkSeedReceipt] | None = None,
    ) -> None:
        if profile not in {LOCAL_PROFILE, CLOUD_PROFILE}:
            raise ValueError(f"{profile} is not a Cursor lane profile")
        self._profile = profile
        self._frames = frames
        self._snapshots = snapshots
        self._branches = branches
        self._scope = request_scope
        self._cap = excerpt_cap_bytes
        self._clock = clock or (lambda: datetime.now(UTC))
        # Idempotent seeds within this process; the payload store is content-addressed
        # across processes (the same transcript bytes name the same artifact).
        self._seeded = seeded if seeded is not None else {}

    @property
    def lane_profile(self) -> str:
        return self._profile

    def for_scope(self, request_scope: str) -> CursorTimeTravel:
        return CursorTimeTravel(
            self._profile,
            self._frames,
            snapshots=self._snapshots,
            branches=self._branches,
            request_scope=request_scope,
            excerpt_cap_bytes=self._cap,
            clock=self._clock,
            seeded=self._seeded,
        )

    # --- shared reads ---------------------------------------------------------------------

    def _scope_of(self, given: str | None = None) -> str:
        scope = given or self._scope
        if scope is None:
            raise TimeTravelUnsupported(self._profile, reason="request_scope_unbound")
        return scope

    def _store(self, scope: str) -> snapshots.SnapshotArtifacts | None:
        if self._snapshots is None:
            return None
        if callable(self._snapshots) and not hasattr(self._snapshots, "retrieve"):
            return self._snapshots(scope)
        return self._snapshots  # type: ignore[return-value]

    async def _generation_frames(
        self, scope: str, harness_execution_id: str, generation: int
    ) -> tuple[ProviderFrame, ...]:
        try:
            execution = UUID(harness_execution_id)
        except ValueError:
            raise TimeTravelUnsupported(self._profile, reason="harness_execution_unknown") from None
        collected: list[ProviderFrame] = []
        after = 0
        for _page in range(_MAX_PAGES):
            page = await self._frames.frames_for_execution(
                scope, execution, generation, after_ordinal=after, limit=_PAGE
            )
            if not page:
                break
            collected.extend(page)
            after = page[-1].arrival_ordinal
            if len(page) < _PAGE:
                break
        return tuple(collected)

    @staticmethod
    def _point_turn(record: CognitionPointRecord) -> tuple[str | None, int | None]:
        """`(turn ref, upper arrival ordinal)` the point stands at."""

        point = record.coordinate.point
        if isinstance(point, SessionCursorPoint):
            upper: int | None = None
            if record.frames is not None:
                upper = record.frames.to_ordinal
            else:
                ordinal = record.channel_facts.get("arrival_ordinal")
                upper = int(ordinal) if isinstance(ordinal, int) else None
            return point.turn_ref, upper
        if isinstance(point, WorkspaceSnapshotPoint):
            return point.turn_ref, None
        raise TimeTravelUnsupported(record.lane_profile, reason="point_kind_not_cursor")

    @staticmethod
    def _snapshot_ref(record: CognitionPointRecord) -> str | None:
        ref = record.workspace_checkpoint_ref
        if ref is None:
            point = record.coordinate.point
            if isinstance(point, WorkspaceSnapshotPoint):
                ref = point.snapshot_ref
            else:
                fact = record.channel_facts.get(TURN_SNAPSHOT_FACT)
                ref = fact if isinstance(fact, str) else None
        return ref

    async def _turn_frames(
        self, scope: str, record: CognitionPointRecord
    ) -> tuple[ProviderFrame, ...]:
        execution = record.coordinate.harness_execution_id
        if execution is None:
            raise TimeTravelUnsupported(self._profile, reason="harness_execution_unknown")
        frames = await self._generation_frames(
            scope, execution, record.coordinate.execution_generation
        )
        turn_ref, upper = self._point_turn(record)
        return tuple(
            frame
            for frame in frames
            if (turn_ref is None or frame.native_turn_ref in {None, turn_ref})
            and (upper is None or frame.arrival_ordinal <= upper)
        )

    async def _files(
        self, scope: str, record: CognitionPointRecord, withheld: list[str]
    ) -> tuple[list[StateFile], dict[str, Any], str | None]:
        """The turn-close workspace files, the snapshot channel and the snapshot ref."""

        ref = self._snapshot_ref(record)
        if ref is None:
            withheld.append("workspace: the turn recorded no snapshot")
            return [], {}, None
        channel: dict[str, Any] = {"snapshot_ref": ref}
        files: list[StateFile] = []
        branch = parse_branch_snapshot(ref)
        if branch is not None:
            channel.update({"kind": "branch", "branch": branch[0], "head": branch[1]})
            repository = record.channel_facts.get("repository")
            if self._branches is None or not isinstance(repository, str):
                withheld.append("workspace files: no branch reader (or repository) composed")
                return files, channel, ref
            channel["repository"] = repository
            try:
                tree = await self._branches.read_tree(
                    repository=repository, ref=branch[1], roots=SNAPSHOT_ROOTS
                )
            except Exception as error:
                withheld.append(f"workspace files: the branch head could not be read ({error})")
                return files, channel, ref
            files.extend(
                StateFile(
                    path=path, size_bytes=len(content), digest=snapshots.bytes_digest(content)
                )
                for path, content in tree
            )
            return files, channel, ref
        store = self._store(scope)
        if store is None:
            withheld.append("workspace files: no snapshot store composed")
            return files, channel, ref
        try:
            manifest = await snapshots.load(ref, store)
        except Exception as error:
            withheld.append(f"workspace files: the snapshot manifest could not be read ({error})")
            return files, channel, ref
        channel.update(
            {
                "kind": "cursor_snapshot",
                "schema_version": manifest.schema_version,
                "base_commit": manifest.base_commit,
                "base_ref": manifest.base_ref,
                "patch_digest": manifest.patch.digest,
                "patch_bytes": manifest.patch.bytes,
                "native": dict(manifest.native),
            }
        )
        seen: set[str] = set()
        for item in (*manifest.files, *manifest.untracked):
            if item.path in seen:
                continue
            seen.add(item.path)
            files.append(StateFile(path=item.path, size_bytes=item.bytes, digest=item.digest))
        return files, channel, ref

    # --- TimeTravelLane --------------------------------------------------------------------

    async def read_as_of(self, record: CognitionPointRecord) -> StateAsOf:
        scope = self._scope_of()
        frames = await self._turn_frames(scope, record)
        transcript = reconstruct_transcript(frames, cap=self._cap)
        withheld = list(transcript.withheld)
        point = record.coordinate.point
        if isinstance(point, SessionCursorPoint) and "leaf" not in record.roles:
            withheld.append("workspace: the files are the turn's close, not this step's")
        files, channel, ref = await self._files(scope, record, withheld)
        level: RestoreLevel = "R2" if files else "R1"
        turn_ref, upper = self._point_turn(record)
        native: dict[str, Any] = {
            "session_ref": getattr(point, "session_ref", None),
            "turn_ref": turn_ref,
            "upper_arrival_ordinal": upper,
            "frames_read": len(frames),
        }
        return StateAsOf(
            point=record,
            restore_level=level,
            history="reconstructed",
            state=GraphStateAsOf(
                messages=tuple(transcript.messages),
                files=tuple(files),
                channels={"workspace_snapshot": channel, "native": native},
                step=record.ordinal,
                source=record.source,
                stamps={"lane_profile": self._profile, **({"snapshot_ref": ref} if ref else {})},
                withheld=tuple(withheld),
            ),
            usage_to_point=dict(transcript.usage),
            observed_at=self._clock(),
        )

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        key = (request.fork_request_id, request.derived_unit_key)
        if key in self._seeded:
            return self._seeded[key]
        scope = self._scope_of(request.request_scope)
        record = request.source
        point = record.coordinate.point
        if not isinstance(point, SessionCursorPoint | WorkspaceSnapshotPoint):
            raise TimeTravelUnsupported(self._profile, reason="point_kind_not_cursor")
        store = self._store(scope)
        if store is None or not hasattr(store, "stage"):
            raise TimeTravelUnsupported(self._profile, reason="snapshot_store_unavailable")
        frames = await self._turn_frames(scope, record)
        transcript = reconstruct_transcript(frames, cap=self._cap)
        snapshot_ref = self._snapshot_ref(record)
        level: RestoreLevel = "R2" if snapshot_ref else "R1"
        session_ref = point.session_ref or ""
        turn_ref = point.turn_ref or ""
        prompt = render_hydration_prompt(
            transcript,
            source_session=session_ref,
            source_turn=turn_ref,
            source_locator=record.coordinate.locator,
            restore_level=level,
            snapshot_ref=snapshot_ref,
            message=request.message,
        )
        transcript_ref = await store.stage(
            request_scope=scope,
            name=f"cursor-seed/{request.fork_request_id}/{request.derived_unit_key}/transcript.md",
            content=prompt.encode("utf-8"),
            media_type="text/markdown",
        )
        count = len(transcript.messages) + (1 if request.message else 0)
        artifacts = {
            SEED_TRANSCRIPT_REF: transcript_ref,
            SEED_SOURCE_SESSION: session_ref,
            SEED_SOURCE_TURN: turn_ref,
            SEED_HEAD: "injected_message" if request.message else "point",
            SEED_HEAD_MESSAGE_COUNT: str(count),
            "lane_profile": self._profile,
        }
        if snapshot_ref:
            artifacts[SEED_SNAPSHOT_REF] = snapshot_ref
        if isinstance(point, SessionCursorPoint) and point.step_ref:
            artifacts[SEED_SOURCE_STEP] = point.step_ref
        derived = CognitionCoordinate(
            run_id=request.derived_run_id,
            unit_key=request.derived_unit_key,
            execution_generation=1,
            point=WorkspaceSnapshotPoint(
                snapshot_ref=snapshot_ref or f"cursor-seed:{request.fork_request_id}",
                session_ref=session_ref or None,
                turn_ref=turn_ref or None,
            ),
        )
        receipt = ForkSeedReceipt(
            restore_level=level,
            history="reconstructed",
            derived=derived,
            copied_checkpoints=0,
            native_artifacts=artifacts,
        )
        self._seeded[key] = receipt
        return receipt

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        """K3 convention: `namespace` is the harness execution id, `checkpointer_ref_digest`
        the generation; the settlement's fold over the persisted frames (the turn-close
        snapshot, which frames do not carry, is not re-derived)."""

        del source_locator
        scope = self._scope_of()
        try:
            generation = int(checkpointer_ref_digest)
        except ValueError:
            raise TimeTravelUnsupported(self._profile, reason="generation_not_numeric") from None
        frames = await self._generation_frames(scope, namespace, generation)
        if not frames:
            return ()
        last_turn = result_locator.split("#")[1] if result_locator.count("#") >= 1 else None
        return fold_generation_points(
            frames,
            collect=cursor_turn_points,
            lane_profile=self._profile,
            harness_execution_id=namespace,
            generation=generation,
            session_ref=frames[0].native_session_ref,
            facts=ClosingFacts(native_status="finished"),
            last_turn_ref=last_turn,
        )


def cursor_time_travel_lanes(
    *,
    frames: FrameReader,
    snapshots: snapshots.SnapshotArtifacts | SnapshotStoreResolver | None = None,
    branches: BranchTreeReader | None = None,
    excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
) -> tuple[CursorTimeTravel, CursorTimeTravel]:
    """Both Cursor profiles' time-travel lanes for a composition's `TimeTravelRegistry.
    register_all(...)`: reads need the frame reader (R1) and the snapshot store or branch
    reader (R2); seeds need a store that stages."""

    return (
        CursorTimeTravel(
            LOCAL_PROFILE, frames, snapshots=snapshots, excerpt_cap_bytes=excerpt_cap_bytes
        ),
        CursorTimeTravel(
            CLOUD_PROFILE,
            frames,
            snapshots=snapshots,
            branches=branches,
            excerpt_cap_bytes=excerpt_cap_bytes,
        ),
    )


__all__ = [
    "HYDRATION_HEADER",
    "SEED_HEAD",
    "SEED_SNAPSHOT_REF",
    "SEED_SOURCE_SESSION",
    "SEED_SOURCE_STEP",
    "SEED_SOURCE_TURN",
    "SEED_TRANSCRIPT_REF",
    "BranchTreeReader",
    "CursorTimeTravel",
    "cursor_time_travel_lanes",
    "reconstruct_transcript",
    "render_hydration_prompt",
]
