"""Codex time travel: `read_as_of`, `seed_fork` and `collect_points` over `thread_item` points.

Cross-provider control (2026-11-05, DESIGN §4.2, §5). The `codex` lane's `TimeTravelLane`:

- `read_as_of` returns the conversation as of the point at the level it can reach. **R1**
  (always): the messages reconstructed from the persisted frames up to the point (agent and
  user messages, command executions, file changes, MCP calls, errors, compactions), bodies
  redacted and bounded, `history: reconstructed`. **R2**: plus the files of the turn's
  continuation workspace snapshot (`codex-workspace:` manifest, digests) when the point names
  one. **R3**: when the source thread is live on this worker (`CodexThreadReader`), the
  items `thread/read` returns up to the point, `history: native`. The level actually reached
  is the receipt's `restore_level`; the describe declares the maximum.
- `seed_fork` creates the derived unit's starting state. The pinned app-server forks a thread
  through a *turn* (`thread/fork` with `lastTurnId`, inclusive; there is no item-level fork
  in codex-cli 0.162.1), so a point that closes a turn (`turn/completed`,
  `turn/completed.result`) forks natively through it (R3, `history: native`); a point inside
  a turn forks through the previous turn and the interrupted turn's steps up to the point
  are reconstructed from the frames into a hydration preamble the derived unit's first turn
  carries (R3, `history: reconstructed`). Without a live source thread (`CodexThreadForker`
  not composed, the thread no longer loaded, or a point inside the first turn) the seed is
  the reconstructed transcript alone, staged as an artifact the derived `start` sends ahead
  of its first turn on a fresh thread (R1). The source thread is never written; repeating a
  fork with the same `fork_request_id` returns the same receipt (in-process memo and
  deterministic artifact names).
- `collect_points` re-derives one generation's points from its persisted frames with the
  same fold the settlement used (`cognition_points.generation_points`).

Reads and seeds need the caller's request scope (frames are tenant-scoped rows):
`ScopedTimeTravelLane.for_scope` binds one. The forked thread's rollout lives in the source
session's `CODEX_HOME`; when the server reports the thread's on-disk path (`Thread.path`,
"[UNSTABLE]" in the pin) the lane stages a copy so the derived session's isolated home can
`thread/resume` it; otherwise the derived `start` resumes only where the home is shared
(owner home mode, the FIXTURE's shared disk) and falls back to a fresh thread with the
hydration preamble.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from uuid import UUID

from mission_control.adapters.codex import cognition_points as points
from mission_control.adapters.codex.protocol import Thread, Turn
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
    StateAsOf,
    StateFile,
    StateMessage,
    ThreadItemPoint,
    ToolCallFact,
)
from mission_control.domain.execution.lanes import RestoreLevel
from mission_control.domain.frames.body import redact_text, redact_value
from mission_control.domain.frames.contracts import (
    DEFAULT_EXCERPT_CAP_BYTES,
    FrameKind,
    ProviderFrame,
)

_LOGGER = logging.getLogger(__name__)
LANE_PROFILE: Final = "codex"
# `continuation.WORKSPACE_SNAPSHOT_PREFIX` (not imported: `continuation` imports the harness,
# which implements this module's provider ports); the unit suite holds the two equal.
WORKSPACE_SNAPSHOT_PREFIX: Final = "codex-workspace:"
SEED_KIND_THREAD_FORK: Final = "thread_fork"
SEED_KIND_TRANSCRIPT: Final = "transcript"
ARTIFACT_LABEL: Final = "codex-time-travel"
TURN_CLOSING_KINDS: Final[frozenset[str]] = frozenset({"turn_ended", "run_result"})
MAX_HYDRATION_MESSAGES: Final = 256
MAX_SNAPSHOT_FILES: Final = 4_096
# Native artifact names (`LaneSeedHead.native_artifacts`; never a credential).
A_SEED_KIND: Final = "seed_kind"
A_SOURCE_THREAD: Final = "source_thread_id"
A_DERIVED_THREAD: Final = "derived_thread_id"
A_LAST_TURN: Final = "last_turn_id"
A_POINT_TURN: Final = "point_turn_id"
A_POINT_ITEM: Final = "point_item_id"
A_HYDRATION_REF: Final = "hydration_ref"
A_ROLLOUT_REF: Final = "rollout_ref"
A_ROLLOUT_RELPATH: Final = "rollout_relpath"
A_SEED_HEAD: Final = "seed_head"


class SeedArtifactStore(Protocol):
    """Content custody for the staged seed (the `SnapshotStore` shape of `continuation.py`)."""

    async def stage(
        self, *, request_scope: str, name: str, content: bytes, media_type: str
    ) -> str: ...

    async def retrieve(self, durable_ref: str) -> bytes: ...


@dataclass(frozen=True)
class ForkedThread:
    """What the app-server created for a `thread/fork`: the new thread and, when the server
    reported it, the rollout file (under the source session's `CODEX_HOME`)."""

    thread_id: str
    rollout_path: str | None = None
    codex_home: str | None = None


class CodexThreadReader(Protocol):
    """R3 reads: the history of a thread this worker holds (`thread/read includeTurns`)."""

    async def thread_history(self, thread_id: str) -> Thread | None: ...


class CodexThreadForker(Protocol):
    """R3 seeds: `thread/fork` of a thread this worker holds, through `last_turn_id`."""

    async def fork_thread(
        self, thread_id: str, *, last_turn_id: str | None, fork_request_id: str
    ) -> ForkedThread | None: ...


class CodexProvider(CodexThreadReader, CodexThreadForker, Protocol):
    """Both provider-side ports (`CodexLocalHarness` implements them)."""


class CodexTimeTravel:
    """`TimeTravelLane` (and `ScopedTimeTravelLane`) for the `codex` lane."""

    def __init__(
        self,
        frames: FrameReader,
        store: SeedArtifactStore | None = None,
        *,
        provider: CodexProvider | None = None,
        request_scope: str | None = None,
        excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
        seeded: dict[str, ForkSeedReceipt] | None = None,
    ) -> None:
        self._frames = frames
        self._store = store
        self._provider = provider
        self._scope = request_scope
        self._cap = excerpt_cap_bytes
        # Idempotency memo per fork request (shared by every scope binding of this lane).
        self._seeded: dict[str, ForkSeedReceipt] = seeded if seeded is not None else {}

    @property
    def lane_profile(self) -> str:
        return LANE_PROFILE

    @property
    def request_scope(self) -> str | None:
        return self._scope

    def for_scope(self, request_scope: str) -> CodexTimeTravel:
        if request_scope == self._scope:
            return self
        return CodexTimeTravel(
            self._frames,
            self._store,
            provider=self._provider,
            request_scope=request_scope,
            excerpt_cap_bytes=self._cap,
            seeded=self._seeded,
        )

    # --- frames -------------------------------------------------------------------------

    def _scope_or_refuse(self, given: str | None = None) -> str:
        scope = given or self._scope
        if scope is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="request_scope_required")
        return scope

    async def _generation_frames(
        self, harness_execution_id: str | None, generation: int, *, scope: str
    ) -> tuple[ProviderFrame, ...]:
        if harness_execution_id is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="execution_unknown")
        try:
            execution = UUID(harness_execution_id)
        except ValueError:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="execution_unknown") from None
        collected: list[ProviderFrame] = []
        after = 0
        while True:
            page = await self._frames.frames_for_execution(
                scope, execution, generation, after_ordinal=after, limit=10_000
            )
            if not page:
                break
            collected.extend(page)
            after = page[-1].arrival_ordinal
            if len(page) < 10_000:
                break
        collected.sort(key=lambda frame: frame.arrival_ordinal)
        return tuple(collected)

    # --- read_as_of ---------------------------------------------------------------------

    async def read_as_of(self, record: CognitionPointRecord) -> StateAsOf:
        point = record.coordinate.point
        if not isinstance(point, ThreadItemPoint):
            raise TimeTravelUnsupported(LANE_PROFILE, reason="point_kind_not_thread_item")
        scope = self._scope_or_refuse()
        frames = await self._generation_frames(
            record.coordinate.harness_execution_id,
            record.coordinate.execution_generation,
            scope=scope,
        )
        cut = _cut_ordinal(record, frames)
        prefix = tuple(frame for frame in frames if frame.arrival_ordinal <= cut)
        if not prefix:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="frames_missing")
        withheld: list[str] = []
        level: RestoreLevel = "R1"
        history = "reconstructed"
        messages: tuple[StateMessage, ...] = ()
        thread_id = point.thread_ref
        item_id = _item_id(record)
        turn_id = _turn_id(record)
        native = await self._thread_history(thread_id)
        if native is not None:
            items = _items_to_point(native, turn_id=turn_id, item_id=item_id)
            if items is not None:
                messages = tuple(self._messages_from_items(items, withheld))
                level, history = "R3", "native"
            else:
                withheld.append("thread history does not hold the point; frames used")
        if level == "R1":
            messages = tuple(self._messages_from_frames(prefix, withheld))
        files, snapshot_ref = await self._snapshot_files(record, scope, withheld)
        if files and level == "R1":
            level = "R2"
        usage: dict[str, int] = {}
        for frame in prefix:
            if frame.kind is FrameKind.USAGE:
                for name, amount in points.usage_of(frame).items():
                    usage[name] = usage.get(name, 0) + amount
        channels: dict[str, Any] = {"thread_id": thread_id}
        if turn_id is not None:
            channels["turn_id"] = turn_id
        if item_id is not None:
            channels["item_id"] = item_id
        status = record.channel_facts.get("turn_status")
        if isinstance(status, str):
            channels["turn_status"] = status
        if snapshot_ref is not None:
            channels["workspace_snapshot_ref"] = snapshot_ref
        withheld.append("secret_values_unknown_at_read: pattern redaction only")
        state = GraphStateAsOf(
            messages=messages,
            files=tuple(files),
            channels=channels,
            step=record.ordinal,
            source=record.source,
            stamps={"lane_profile": LANE_PROFILE, "frames_to_ordinal": cut},
            withheld=tuple(dict.fromkeys(withheld)),
        )
        return StateAsOf(
            point=record,
            restore_level=level,
            history=history,
            state=state,
            usage_to_point=usage,
            observed_at=datetime.now(UTC),
        )

    async def _thread_history(self, thread_id: str) -> Thread | None:
        if self._provider is None:
            return None
        try:
            return await self._provider.thread_history(thread_id)
        except Exception:  # a provider that cannot answer is an R1 read, never a failure
            _LOGGER.warning("codex thread %s history unreadable; frames used", thread_id)
            return None

    async def _snapshot_files(
        self, record: CognitionPointRecord, scope: str, withheld: list[str]
    ) -> tuple[list[StateFile], str | None]:
        ref = record.workspace_checkpoint_ref
        if not isinstance(ref, str) or not ref.startswith(WORKSPACE_SNAPSHOT_PREFIX):
            facts_ref = record.channel_facts.get("workspace_snapshot_ref")
            ref = facts_ref if isinstance(facts_ref, str) else None
        if ref is None or not ref.startswith(WORKSPACE_SNAPSHOT_PREFIX):
            return [], None
        if self._store is None:
            withheld.append("workspace snapshot unread: no artifact store composed")
            return [], ref
        del scope
        try:
            raw = await self._store.retrieve(ref.removeprefix(WORKSPACE_SNAPSHOT_PREFIX))
            body = json.loads(raw)
        except (LookupError, ValueError):
            withheld.append("workspace snapshot unread: manifest not retrievable")
            return [], ref
        manifest = body.get("manifest") if isinstance(body, Mapping) else None
        durable = body.get("durable_refs") if isinstance(body, Mapping) else None
        files: list[StateFile] = []
        if isinstance(manifest, Mapping):
            for path, digest in sorted(manifest.items())[:MAX_SNAPSHOT_FILES]:
                if not isinstance(path, str) or not isinstance(digest, str):
                    continue
                size = _size_of(durable.get(path) if isinstance(durable, Mapping) else None)
                try:
                    files.append(
                        StateFile(path=path, size_bytes=size, digest=digest, source="closure")
                    )
                except ValueError:
                    continue
        if files:
            withheld.append("workspace files: digests from the snapshot manifest, no bytes")
        return files, ref

    # --- rendering -----------------------------------------------------------------------

    def _messages_from_frames(
        self, frames: Sequence[ProviderFrame], withheld: list[str]
    ) -> list[StateMessage]:
        rendered: list[StateMessage] = []
        for frame in frames:
            if frame.subordinate_ref is not None:
                continue
            body = points.body_of(frame)
            if frame.kind is FrameKind.MESSAGE or frame.kind in {
                FrameKind.TOOL_CALL_COMPLETED,
                FrameKind.TOOL_CALL_FAILED,
            }:
                item = body.get("item")
                if not isinstance(item, Mapping):
                    withheld.append(f"frame {frame.arrival_ordinal} body excerpted; item withheld")
                    rendered.append(
                        self._message(
                            "tool" if frame.kind is not FrameKind.MESSAGE else "assistant",
                            None,
                            id=points.item_id_of(frame),
                            name=None,
                            withheld=True,
                        )
                    )
                    continue
                message = self._message_from_item(item)
                if message is not None:
                    rendered.append(message)
            elif frame.kind is FrameKind.ERROR:
                error = body.get("error")
                text = error.get("message") if isinstance(error, Mapping) else None
                rendered.append(
                    self._message("system", str(text or "provider error"), name="error")
                )
            elif frame.kind is FrameKind.AFTER_COMPACTION:
                rendered.append(self._message("system", "context compacted", name="compaction"))
        return rendered[-MAX_HYDRATION_MESSAGES:]

    def _messages_from_items(
        self, items: Sequence[Mapping[str, Any]], withheld: list[str]
    ) -> list[StateMessage]:
        del withheld
        rendered: list[StateMessage] = []
        for item in items:
            message = self._message_from_item(item)
            if message is not None:
                rendered.append(message)
        return rendered[-MAX_HYDRATION_MESSAGES:]

    def _message_from_item(self, item: Mapping[str, Any]) -> StateMessage | None:
        kind = str(item.get("type") or "")
        item_id = item.get("id")
        identity = str(item_id) if isinstance(item_id, str) else None
        if kind == "agentMessage":
            text = item.get("text")
            return self._message("assistant", text if isinstance(text, str) else None, id=identity)
        if kind == "userMessage":
            return self._message("user", _content_text(item.get("content")), id=identity)
        if kind == "commandExecution":
            command = str(item.get("command") or "")
            output = item.get("aggregatedOutput")
            exit_code = item.get("exitCode")
            text = f"$ {command}\n{output if isinstance(output, str) else ''}".rstrip()
            if exit_code is not None:
                text += f"\n[exit {exit_code}]"
            return self._message(
                "tool",
                text,
                id=identity,
                name="commandExecution",
                tool_call_id=identity,
                tool_calls=(
                    ToolCallFact(
                        id=identity, name="commandExecution", arguments={"command": command}
                    )
                    if command
                    else None
                ),
            )
        if kind == "fileChange":
            changes = item.get("changes")
            paths = (
                [str(change.get("path")) for change in changes if isinstance(change, Mapping)]
                if isinstance(changes, list)
                else []
            )
            return self._message(
                "tool",
                "\n".join(paths) or None,
                id=identity,
                name="fileChange",
                tool_call_id=identity,
                tool_calls=ToolCallFact(id=identity, name="fileChange", arguments={"paths": paths}),
            )
        if kind in {"mcpToolCall", "dynamicToolCall", "webSearch", "collabAgentToolCall"}:
            name = str(item.get("tool") or item.get("name") or kind)
            arguments = item.get("arguments")
            result = item.get("result")
            return self._message(
                "tool",
                json.dumps(result, sort_keys=True, default=str) if result is not None else None,
                id=identity,
                name=name,
                tool_call_id=identity,
                tool_calls=ToolCallFact(
                    id=identity,
                    name=name,
                    arguments=dict(arguments) if isinstance(arguments, Mapping) else None,
                ),
            )
        if kind == "contextCompaction":
            return self._message("system", "context compacted", id=identity, name="compaction")
        return None

    def _message(
        self,
        role: str,
        text: str | None,
        *,
        id: str | None = None,  # noqa: A002 - the StateMessage field
        name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: ToolCallFact | None = None,
        withheld: bool = False,
    ) -> StateMessage:
        redacted, redactions = redact_text(text) if text else ("", ())
        encoded = redacted.encode("utf-8")
        truncated = len(encoded) > self._cap
        calls: tuple[ToolCallFact, ...] = ()
        if tool_calls is not None:
            arguments, _found = redact_value(tool_calls.arguments)
            canonical = points.canonical(arguments)
            oversized = len(canonical.encode("utf-8")) > self._cap
            calls = (
                ToolCallFact(
                    id=tool_calls.id,
                    name=tool_calls.name,
                    arguments=None if oversized else (dict(arguments) if arguments else None),
                    arguments_digest=(
                        "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    ),
                    arguments_bytes=len(canonical.encode("utf-8")),
                    truncated=oversized,
                ),
            )
        return StateMessage(
            id=id,
            role=role,
            name=name,
            tool_call_id=tool_call_id,
            tool_calls=calls,
            text=encoded[: self._cap].decode("utf-8", errors="ignore") if text else None,
            text_bytes=len(encoded),
            text_digest=("sha256:" + hashlib.sha256(encoded).hexdigest()) if text else None,
            truncated=truncated or withheld,
            redactions=len(redactions),
        )

    # --- seed_fork ------------------------------------------------------------------------

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        memo = self._seeded.get(request.fork_request_id)
        if memo is not None:
            return memo
        record = request.source
        point = record.coordinate.point
        if not isinstance(point, ThreadItemPoint):
            raise TimeTravelUnsupported(LANE_PROFILE, reason="point_kind_not_thread_item")
        scope = self._scope_or_refuse(request.request_scope)
        frames = await self._generation_frames(
            record.coordinate.harness_execution_id,
            record.coordinate.execution_generation,
            scope=scope,
        )
        cut = _cut_ordinal(record, frames)
        prefix = tuple(frame for frame in frames if frame.arrival_ordinal <= cut)
        thread_id = point.thread_ref
        turn_id = _turn_id(record) or next(
            (frame.native_turn_ref for frame in reversed(prefix) if frame.native_turn_ref), None
        )
        closes_turn = str(record.channel_facts.get("frame_kind") or "") in TURN_CLOSING_KINDS
        order = points.turn_order(frames)
        previous: str | None = None
        if turn_id is not None and turn_id in order:
            index = order.index(turn_id)
            previous = order[index - 1] if index > 0 else None
        last_turn = turn_id if closes_turn else previous
        forked: ForkedThread | None = None
        if self._provider is not None and last_turn is not None:
            try:
                forked = await self._provider.fork_thread(
                    thread_id, last_turn_id=last_turn, fork_request_id=request.fork_request_id
                )
            except Exception:
                _LOGGER.warning("codex thread/fork of %s failed; transcript seed used", thread_id)
                forked = None
        artifacts: dict[str, str] = {
            A_SOURCE_THREAD: thread_id,
            A_POINT_ITEM: point.item_ref,
        }
        if turn_id is not None:
            artifacts[A_POINT_TURN] = turn_id
        withheld: list[str] = []
        if forked is not None:
            artifacts[A_SEED_KIND] = SEED_KIND_THREAD_FORK
            artifacts[A_DERIVED_THREAD] = forked.thread_id
            artifacts[A_LAST_TURN] = str(last_turn)
            hydrated = (
                ()
                if closes_turn
                else self._messages_from_frames(
                    tuple(frame for frame in prefix if frame.native_turn_ref == turn_id), withheld
                )
            )
            level: RestoreLevel = "R3"
            history = "native" if closes_turn else "reconstructed"
            await self._stage_rollout(forked, artifacts, scope, request.fork_request_id)
        else:
            artifacts[A_SEED_KIND] = SEED_KIND_TRANSCRIPT
            hydrated = self._messages_from_frames(prefix, withheld)
            level, history = "R1", "reconstructed"
        if hydrated or request.message is not None:
            text = hydration_text(hydrated, message=request.message, source_thread=thread_id)
            artifacts[A_HYDRATION_REF] = await self._stage(
                scope,
                f"{ARTIFACT_LABEL}/{request.fork_request_id}/hydration.md",
                text.encode("utf-8"),
                "text/markdown",
            )
        if request.message is not None:
            artifacts[A_SEED_HEAD] = "injected_message"
        artifacts[SEED_HEAD_MESSAGE_COUNT] = str(len(hydrated) + (1 if request.message else 0))
        derived = CognitionCoordinate(
            run_id=request.derived_run_id,
            unit_key=request.derived_unit_key,
            execution_generation=1,
            point=ThreadItemPoint(
                thread_ref=(
                    forked.thread_id if forked is not None else f"seed:{request.fork_request_id}"
                )[:512],
                item_ref=f"fork-seed:{request.fork_request_id}"[:512],
            ),
        )
        receipt = ForkSeedReceipt(
            restore_level=level,
            history=history,
            derived=derived,
            copied_checkpoints=len(hydrated),
            native_artifacts=artifacts,
        )
        self._seeded[request.fork_request_id] = receipt
        return receipt

    async def _stage(self, scope: str, name: str, content: bytes, media_type: str) -> str:
        if self._store is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="artifact_store_required")
        return await self._store.stage(
            request_scope=scope, name=name, content=content, media_type=media_type
        )

    async def _stage_rollout(
        self, forked: ForkedThread, artifacts: dict[str, str], scope: str, fork_request_id: str
    ) -> None:
        """Copy the forked thread's rollout (when the server named it and it is readable
        here) so an isolated derived `CODEX_HOME` can resume it; never a credential file."""

        if forked.rollout_path is None or self._store is None:
            return
        rollout = Path(forked.rollout_path)
        try:
            content = await asyncio.to_thread(rollout.read_bytes)
        except OSError:
            return
        relative = rollout.name
        if forked.codex_home:
            try:
                relative = rollout.relative_to(Path(forked.codex_home)).as_posix()
            except ValueError:
                relative = f"sessions/{rollout.name}"
        artifacts[A_ROLLOUT_RELPATH] = relative
        artifacts[A_ROLLOUT_REF] = await self._stage(
            scope,
            f"{ARTIFACT_LABEL}/{fork_request_id}/{rollout.name}",
            content,
            "application/jsonl",
        )

    # --- collect_points ---------------------------------------------------------------------

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        """K3 convention: `namespace` = harness execution id, `checkpointer_ref_digest` = the
        generation; the same fold the settlement used, over the persisted frames."""

        scope = self._scope_or_refuse()
        try:
            generation = int(checkpointer_ref_digest)
        except ValueError:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="generation_not_numeric") from None
        frames = await self._generation_frames(namespace, generation, scope=scope)
        if not frames:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="frames_missing")
        observed = points.generation_points(
            frames,
            harness_execution_id=namespace,
            generation=generation,
            facts=points.closing_facts_of(frames),
        )
        locators = [item.locator for item in observed]
        start = locators.index(source_locator) + 1 if source_locator in locators else 0
        end = locators.index(result_locator) + 1 if result_locator in locators else len(observed)
        return tuple(observed[start:end])


# --- helpers -----------------------------------------------------------------------------


def _item_id(record: CognitionPointRecord) -> str | None:
    value = record.channel_facts.get("item_id")
    return value if isinstance(value, str) and value else None


def _turn_id(record: CognitionPointRecord) -> str | None:
    value = record.channel_facts.get("turn_id")
    return value if isinstance(value, str) and value else None


def _cut_ordinal(record: CognitionPointRecord, frames: Sequence[ProviderFrame]) -> int:
    """The last arrival ordinal of the point's step: the settlement's frame range, else the
    boundary frame's ordinal the fold recorded, else the frame that closes the item."""

    if record.frames is not None:
        return record.frames.to_ordinal
    ordinal = record.channel_facts.get("arrival_ordinal")
    if isinstance(ordinal, int) and not isinstance(ordinal, bool):
        return ordinal
    point = record.coordinate.point
    if isinstance(point, ThreadItemPoint):
        for frame in frames:
            if points.item_ref_for(frame) == point.item_ref:
                return frame.arrival_ordinal
    return frames[-1].arrival_ordinal if frames else 0


def _items_to_point(
    thread: Thread, *, turn_id: str | None, item_id: str | None
) -> list[Mapping[str, Any]] | None:
    """The thread's items in order up to the point (inclusive), or None when the history
    does not hold it (the turn or item is unknown to the server)."""

    collected: list[Mapping[str, Any]] = []
    for turn in thread.turns:
        if isinstance(turn, Turn):
            items = turn.items
            this_turn = turn.id
        else:  # pragma: no cover - the pinned model always parses turns
            continue
        for item in items:
            collected.append(item)
            if item_id is not None and item.get("id") == item_id:
                return collected
        if turn_id is not None and this_turn == turn_id and item_id is None:
            return collected
    return None if (item_id is not None or turn_id is not None) else collected


def _content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(block.get("text"))
            for block in content
            if isinstance(block, Mapping) and isinstance(block.get("text"), str)
        ]
        return "\n".join(parts) if parts else None
    return None


def _size_of(durable_ref: Any) -> int:
    """`<object_ref>#<sha256>:<size>` carries the size; anything else is unknown (0)."""

    if not isinstance(durable_ref, str) or "#" not in durable_ref:
        return 0
    _object, _sep, rest = durable_ref.partition("#")
    _digest, _sep2, size = rest.rpartition(":")
    return int(size) if size.isdigit() else 0


def hydration_text(
    messages: Sequence[StateMessage], *, message: str | None, source_thread: str
) -> str:
    """The preamble a derived unit's first turn carries: the reconstructed steps to the point
    (redacted, bounded) and the injected human message, labelled as history, never as a
    new instruction set."""

    lines = [
        "# Forked session history",
        "",
        f"The following steps were reconstructed from thread `{source_thread}` up to the fork",
        "point. They are history, not new instructions.",
        "",
    ]
    for item in messages:
        head = f"## {item.role}" + (f" ({item.name})" if item.name else "")
        lines.append(head)
        if item.tool_calls:
            for call in item.tool_calls:
                lines.append(f"- call `{call.name}` {points.canonical(call.arguments or {})}")
        if item.text:
            lines.append("")
            lines.append(item.text)
        lines.append("")
    if message is not None:
        lines.extend(["# Injected message", "", message, ""])
    return "\n".join(lines)


__all__ = [
    "ARTIFACT_LABEL",
    "A_DERIVED_THREAD",
    "A_HYDRATION_REF",
    "A_LAST_TURN",
    "A_POINT_ITEM",
    "A_POINT_TURN",
    "A_ROLLOUT_REF",
    "A_ROLLOUT_RELPATH",
    "A_SEED_HEAD",
    "A_SEED_KIND",
    "A_SOURCE_THREAD",
    "LANE_PROFILE",
    "SEED_KIND_THREAD_FORK",
    "SEED_KIND_TRANSCRIPT",
    "WORKSPACE_SNAPSHOT_PREFIX",
    "CodexProvider",
    "CodexThreadForker",
    "CodexThreadReader",
    "CodexTimeTravel",
    "ForkedThread",
    "SeedArtifactStore",
    "hydration_text",
]
