"""Deep Agents time travel: `read_as_of` at R3 over the registered saver (P1 turn 4).

The lane's implementation of the `TimeTravelLane` port for `checkpoint` points. `read_as_of`
opens the root checkpoint by qualified key, folds the delta channels (`messages`) the way
`add_messages` would, and returns the graph state at that point with secrets and oversized
content hidden (owner decision Q2, 2026-10-21): every message with its role, name, tool
calls and text through the frame body redactor under the excerpt cap; every `files` entry
with its size and digest; the other state channels as redacted values; the pending tasks,
interrupts, step, source and lineage stamps. It never builds an agent and never writes.
`seed_fork` (copy the thread, branch in the copy at the point) is the WP-2 half of the port.

1.4.4 (TR-D8): every `files` entry says where it lived (`source`): the `files` state channel
the checkpoint holds, or a sandbox upload the attempt's materialization manifest names
(digest and size, no contents). The manifest is the `environment_materialized` frame of the
point's execution, read through a `MaterializationManifestReader` when composition gives one
(`FrameStoreManifestReader` over the frame repository); without one the read says so in
`withheld` and keeps the digest only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

import psycopg
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.base.id import uuid6
from langgraph.checkpoint.serde.types import _DeltaSnapshot

from mission_control.adapters.deep_agents.checkpoint_history import _pending_task_names
from mission_control.adapters.deep_agents.checkpoint_reads import root_checkpoint_config
from mission_control.adapters.deep_agents.cognition_points import (
    fold_delta_history,
    walk_points,
)
from mission_control.adapters.deep_agents.frames import (
    SOURCE_SANDBOX_UPLOAD,
    SOURCE_STATE_CHANNEL,
)
from mission_control.application.execution.harness.time_travel import (
    SEED_HEAD_MESSAGE_COUNT,
    ForkSeedReceipt,
    ForkSeedRequest,
    TimeTravelUnsupported,
)
from mission_control.application.frames.sink import FrameReader
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointObservation,
    CognitionPointRecord,
    GraphStateAsOf,
    StateAsOf,
    StateFile,
    StateMessage,
    ToolCallFact,
)
from mission_control.domain.frames.body import (
    frame_body_object,
    jsonable,
    redact_text,
    redact_value,
)
from mission_control.domain.frames.contracts import DEFAULT_EXCERPT_CAP_BYTES, FrameKind
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey

LANE_PROFILE = "deep_agents"
MAX_COPY_WALK = 4_096
# 1.4.4 (P6.1): the wall-clock budget of one seed copy.
DEFAULT_COPY_BUDGET_SECONDS = 120.0
MAX_CHANNEL_BYTES = 65_536
MAX_INTERRUPTS = 64
STAMP_PREFIX = "belllabs_"
# 1.4.4 (P5.3): the metadata stamp of a seed head that carries an injected message.
FORK_SEED_STAMP = "belllabs_fork_seed"
_DIGEST_PATTERN_PREFIX = "sha256:"


class MaterializationManifestReader(Protocol):
    """Reads the `environment_materialized` manifest of one harness execution generation."""

    async def manifest(
        self, harness_execution_id: str, generation: int
    ) -> Mapping[str, Any] | None: ...


class FrameStoreManifestReader:
    """The manifest reader over a frame repository, for one request scope: the complete body
    of the execution's `environment_materialized` frame, or None when the frame is absent or
    its body was excerpted (promoted bodies need the artifact reader; the digest stays)."""

    def __init__(self, frames: FrameReader, *, request_scope: str) -> None:
        self._frames = frames
        self._scope = request_scope

    async def manifest(
        self, harness_execution_id: str, generation: int
    ) -> Mapping[str, Any] | None:
        try:
            execution = UUID(harness_execution_id)
        except ValueError:
            return None
        frames = await self._frames.frames_for_execution(self._scope, execution, generation)
        for frame in frames:
            if frame.kind is not FrameKind.ENVIRONMENT_MATERIALIZED:
                continue
            body = frame_body_object(frame.body_excerpt, frame.body_bytes)
            return body or None
        return None


class DeepAgentsTimeTravel:
    """`TimeTravelLane` for the Deep Agents lane over the worker's registered savers."""

    def __init__(
        self,
        checkpointers: Mapping[str, BaseCheckpointSaver[Any]],
        *,
        excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
        manifests: MaterializationManifestReader | None = None,
        locators: Mapping[str, str] | None = None,
        copy_budget_seconds: float = DEFAULT_COPY_BUDGET_SECONDS,
    ) -> None:
        self._checkpointers = checkpointers
        self._cap = excerpt_cap_bytes
        self._manifests = manifests
        # 1.4.4 (P6.1): the wall-clock budget of one seed copy; past it the copy stops with
        # `copy_incomplete` (retryable: a retry re-puts what is there and continues).
        self._copy_budget = copy_budget_seconds
        # 1.4.4 (P6.2): the locator digest each registered saver serves; a point whose key
        # names another location is refused (`saver_not_served`), never read elsewhere.
        self._locators = dict(locators or {})

    def _saver_for(self, key: QualifiedCheckpointKey) -> BaseCheckpointSaver[Any]:
        saver = self._checkpointers.get(key.checkpointer_ref_digest)
        if saver is None:
            raise TimeTravelUnsupported(
                LANE_PROFILE,
                reason="checkpointer_not_registered",
                saver=key.checkpointer_ref_digest,
            )
        served = self._locators.get(key.checkpointer_ref_digest)
        if key.saver_locator_digest is not None and key.saver_locator_digest != served:
            raise TimeTravelUnsupported(
                LANE_PROFILE, reason="saver_not_served", saver=key.checkpointer_ref_digest
            )
        return saver

    @property
    def lane_profile(self) -> str:
        return LANE_PROFILE

    async def read_as_of(self, record: CognitionPointRecord) -> StateAsOf:
        point = record.coordinate.point
        if not isinstance(point, CheckpointPoint):
            raise TimeTravelUnsupported(LANE_PROFILE, reason="point_kind_not_checkpoint")
        key = point.key
        saver = self._saver_for(key)
        with _saver_outcome(key.checkpointer_ref_digest):
            return await self._read_as_of(saver, record, key)

    async def _read_as_of(
        self,
        saver: BaseCheckpointSaver[Any],
        record: CognitionPointRecord,
        key: QualifiedCheckpointKey,
    ) -> StateAsOf:
        config = _point_config(key)
        item = await saver.aget_tuple(config)
        if item is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="checkpoint_missing")
        checkpoint = item.checkpoint
        stored = checkpoint.get("channel_values") or {}
        # Tracing Stage 3 (R2-1): a delta channel's periodic snapshot (`_DeltaSnapshot`, every
        # 50 updates on Deep Agents' `messages` and `files`) is the value at this checkpoint.
        values: dict[str, Any] = {
            name: _snapshot_value(value) for name, value in stored.items() if not _internal(name)
        }
        delta_channels = [
            name
            for name in checkpoint.get("channel_versions") or {}
            if not _internal(name) and name not in values
        ]
        if delta_channels:
            histories = await saver.aget_delta_channel_history(
                config=config, channels=delta_channels
            )
            for name, history in histories.items():
                values[name] = fold_delta_history(history)
        withheld: list[str] = []
        messages = tuple(
            self._message(message, withheld)
            for message in values.pop("messages", []) or []
            if isinstance(message, BaseMessage)
        )
        files = [_file(path, data) for path, data in sorted(_files(values.pop("files", None)))]
        # 1.4.4 (TR-D8): the sandbox uploads the materialization manifest names, beside the
        # state channel (digests only; the sandbox is not read here).
        manifest_digest = _manifest_digest(record)
        manifest = await self._manifest_for(record)
        if manifest is None:
            withheld.append(
                "materialization manifest unread: no manifest reader composed"
                if self._manifests is None
                else "materialization manifest unread: environment frame not reachable"
            )
        else:
            if manifest_digest is None:
                manifest_digest = _manifest_digest_of(manifest)
            files.extend(_uploaded_files(manifest))
        channels: dict[str, Any] = {}
        for name, value in sorted(values.items()):
            if name == "structured_response":
                channels[name] = _bounded(value, self._cap, withheld, name)
                continue
            channels[name] = _bounded(value, MAX_CHANNEL_BYTES, withheld, name)
        interrupts = tuple(
            _bounded(write[2], self._cap, withheld, "__interrupt__")
            for write in (item.pending_writes or ())[:MAX_INTERRUPTS]
            if len(write) >= 3 and write[1] == "__interrupt__"
        )
        metadata = dict(item.metadata or {})
        stamps = {
            name: value
            for name, value in metadata.items()
            if name.startswith(STAMP_PREFIX) and isinstance(value, str | int)
        }
        step = metadata.get("step")
        source = metadata.get("source")
        withheld.append("secret_values_unknown_at_read: pattern redaction only")
        state = GraphStateAsOf(
            messages=messages,
            files=tuple(files),
            channels=channels,
            pending_tasks=_pending_task_names(checkpoint),
            interrupts=tuple(
                dict(value) if isinstance(value, Mapping) else {"value": value}
                for value in interrupts
            ),
            step=step if isinstance(step, int) else None,
            source=str(source) if source is not None else None,
            stamps=stamps,
            withheld=tuple(withheld),
        )
        usage: dict[str, int] = {}
        for message in messages:
            for name, amount in message.usage.items():
                usage[name] = usage.get(name, 0) + amount
        return StateAsOf(
            point=record,
            restore_level="R3",
            history="native",
            state=state,
            usage_to_point=usage,
            materialization_digest=manifest_digest,
            observed_at=datetime.now(UTC),
        )

    async def _manifest_for(self, record: CognitionPointRecord) -> Mapping[str, Any] | None:
        execution = record.coordinate.harness_execution_id
        if self._manifests is None or execution is None:
            return None
        return await self._manifests.manifest(execution, record.coordinate.execution_generation)

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        """Copy the source thread's root lineage up to the point into the derived namespace.

        Every root checkpoint from the thread root to the point is re-put under the derived
        `thread_id` with the same checkpoint ids, metadata and parent links, and each one's
        pending writes (the `messages` delta history) follows it, so the saver reconstructs
        the state at the point exactly as the source thread would. Nothing after the point
        is copied and the source thread is never written: the derived unit's first attempt
        pins to the point and continues from it (`not_submitted` with an expected source).
        The copy is idempotent: a derived thread that already holds the point is left alone.
        With an injected message (Tracing Stage 3, R2-1) the point's own pending writes (the
        source's next step) are not copied: the seed head after the point folds them in.
        """

        point = request.source.coordinate.point
        if not isinstance(point, CheckpointPoint):
            raise TimeTravelUnsupported(LANE_PROFILE, reason="point_kind_not_checkpoint")
        key = point.key
        saver = self._saver_for(key)
        with _saver_outcome(key.checkpointer_ref_digest):
            return await self._seed_fork(saver, request, key)

    async def _seed_fork(
        self,
        saver: BaseCheckpointSaver[Any],
        request: ForkSeedRequest,
        key: QualifiedCheckpointKey,
    ) -> ForkSeedReceipt:
        target = request.derived_namespace
        deadline = time.monotonic() + self._copy_budget
        lineage: list[Any] = []
        cursor: str | None = key.checkpoint_id
        while cursor is not None:
            if len(lineage) >= MAX_COPY_WALK:
                raise TimeTravelUnsupported(LANE_PROFILE, reason="lineage_exceeds_copy_bound")
            if time.monotonic() > deadline:
                raise TimeTravelUnsupported(
                    LANE_PROFILE, reason="copy_incomplete", saver=key.checkpointer_ref_digest
                )
            item = await saver.aget_tuple(root_checkpoint_config(key.thread_id, cursor))
            if item is None:
                raise TimeTravelUnsupported(LANE_PROFILE, reason="checkpoint_missing")
            lineage.append(item)
            parent = item.parent_config
            parent_id = (
                parent.get("configurable", {}).get("checkpoint_id")
                if isinstance(parent, Mapping)
                else None
            )
            cursor = str(parent_id) if parent_id else None
        lineage.reverse()
        head = lineage[-1]
        stamps = dict(head.metadata or {})
        binding_digest = stamps.get("belllabs_binding_digest")
        state_schema_digest = stamps.get("belllabs_state_schema_digest")
        if not isinstance(binding_digest, str) or not isinstance(state_schema_digest, str):
            raise TimeTravelUnsupported(LANE_PROFILE, reason="point_not_stamped")
        existing = await saver.aget_tuple(root_checkpoint_config(target, key.checkpoint_id))
        copied = 0
        if existing is None:
            previous: str | None = None
            for index, item in enumerate(lineage):
                if time.monotonic() > deadline:
                    raise TimeTravelUnsupported(
                        LANE_PROFILE, reason="copy_incomplete", saver=key.checkpointer_ref_digest
                    )
                config: dict[str, Any] = {
                    "configurable": {
                        "thread_id": target,
                        "checkpoint_ns": "",
                        **({"checkpoint_id": previous} if previous is not None else {}),
                    }
                }
                checkpoint = dict(item.checkpoint)
                versions = dict(checkpoint.get("channel_versions") or {})
                await saver.aput(
                    cast(RunnableConfig, config),
                    cast(Checkpoint, checkpoint),
                    cast(CheckpointMetadata, dict(item.metadata or {})),
                    versions,
                )
                this_config = root_checkpoint_config(target, str(checkpoint["id"]))
                by_task: dict[tuple[str, str], list[tuple[str, Any]]] = {}
                # Tracing Stage 3 (R2-1): the point's own pending writes are the outputs of
                # the source's *next* step. Deep Agents' `messages` and `files` are delta
                # channels, so a child of the point folds them in: with an injected message
                # the seed head is that child, and it must be the state at the point plus the
                # message, never the next step's output. Without a message the copy is
                # unchanged (the derived attempt continues from the point itself).
                head_of_injection = request.message is not None and index == len(lineage) - 1
                for write in () if head_of_injection else item.pending_writes or ():
                    task_id, channel, value = str(write[0]), str(write[1]), write[2]
                    task_path = str(write[3]) if len(write) > 3 else ""
                    by_task.setdefault((task_id, task_path), []).append((channel, value))
                for (task_id, task_path), writes in by_task.items():
                    await saver.aput_writes(this_config, writes, task_id, task_path)
                previous = str(checkpoint["id"])
                copied += 1
            verify = await saver.aget_tuple(root_checkpoint_config(target, key.checkpoint_id))
            if verify is None:
                raise TimeTravelUnsupported(LANE_PROFILE, reason="copy_not_readable")
        head_id, head_parent = key.checkpoint_id, key.parent_checkpoint_id
        artifacts = {
            "binding_digest": binding_digest,
            "state_schema_digest": state_schema_digest,
            "source_thread_id": key.thread_id,
            "derived_thread_id": target,
        }
        if request.message is not None:
            # 1.4.4 (P5.3): one more root checkpoint on the derived thread whose `messages`
            # write is the injected human message, stamped like the point; it becomes the
            # seeded head the derived unit's first attempt pins to.
            head_id = await self._inject_message(
                saver,
                thread_id=target,
                point_id=key.checkpoint_id,
                message=request.message,
                fork_request_id=request.fork_request_id,
            )
            head_parent = key.checkpoint_id
            artifacts["seed_head"] = "injected_message"
            # Tracing Stage 3 (R2-1): the head's message count as the saver folds it, so
            # the `fork_seed` point records what the head holds rather than a guess.
            count = await _message_count(saver, target, head_id)
            if count is not None:
                artifacts[SEED_HEAD_MESSAGE_COUNT] = str(count)
        derived = CognitionCoordinate(
            run_id=request.derived_run_id,
            unit_key=request.derived_unit_key,
            execution_generation=1,
            point=CheckpointPoint(
                key=QualifiedCheckpointKey(
                    checkpointer_ref_digest=key.checkpointer_ref_digest,
                    thread_id=target,
                    checkpoint_ns="",
                    checkpoint_id=head_id,
                    parent_checkpoint_id=head_parent,
                    saver_locator_digest=self._locators.get(key.checkpointer_ref_digest),
                )
            ),
        )
        return ForkSeedReceipt(
            restore_level="R3",
            history="native",
            derived=derived,
            copied_checkpoints=copied,
            native_artifacts=artifacts,
        )

    @staticmethod
    async def _inject_message(
        saver: BaseCheckpointSaver[Any],
        *,
        thread_id: str,
        point_id: str,
        message: str,
        fork_request_id: str,
    ) -> str:
        """The seed head: the message as a `messages` write of the copied point (the delta
        history of the next checkpoint folds it in) and a new root checkpoint after the
        point with the `messages` version advanced and the point's stamps copied.
        Idempotent: a head already stamped with this fork request is reused.

        Tracing Stage 3 (R2-1): the head folds every write stored on the point, so the copy
        (`_seed_fork`) leaves the point's own pending writes (the source's next step) out of
        the derived thread; the head is then exactly the state at the point plus the
        message."""

        thread_config: RunnableConfig = {
            "configurable": {"thread_id": thread_id, "checkpoint_ns": ""}
        }
        async for item in saver.alist(
            thread_config, filter={FORK_SEED_STAMP: fork_request_id}, limit=1
        ):
            return str(item.checkpoint["id"])
        point_config = root_checkpoint_config(thread_id, point_id)
        point = await saver.aget_tuple(point_config)
        if point is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="checkpoint_missing")
        injected = HumanMessage(content=message, id=f"fork-seed:{fork_request_id}")
        await saver.aput_writes(
            point_config, [("messages", [injected])], f"fork-seed:{fork_request_id}", ""
        )
        versions = dict(point.checkpoint.get("channel_versions") or {})
        versions["messages"] = saver.get_next_version(versions.get("messages"), None)
        checkpoint = dict(point.checkpoint)
        values: dict[str, Any] = dict(point.checkpoint.get("channel_values") or {})
        if _is_snapshot(values.get("messages")):
            # Tracing Stage 3 (R2-1): a delta snapshot at the point is the point's value; the
            # head (a new `messages` version) folds it with the point's write, so it holds no
            # blob of its own.
            values.pop("messages")
        elif "messages" in values:
            # A stored (non-delta) `messages` channel: the head holds the appended list; a
            # delta channel folds the point's pending write instead.
            values["messages"] = [*list(values["messages"] or []), injected]
        checkpoint.update(
            {
                "id": str(uuid6(clock_seq=-2)),
                "ts": datetime.now(UTC).isoformat(),
                "channel_values": values,
                "channel_versions": versions,
                "versions_seen": dict(point.checkpoint.get("versions_seen") or {}),
                "updated_channels": ["messages"],
            }
        )
        metadata = dict(point.metadata or {})
        step = metadata.get("step")
        metadata.update(
            {
                "source": "fork",
                "step": (step + 1) if isinstance(step, int) else 0,
                "parents": {},
                FORK_SEED_STAMP: fork_request_id,
            }
        )
        await saver.aput(
            point_config,
            cast(Checkpoint, checkpoint),
            cast(CheckpointMetadata, metadata),
            {"messages": versions["messages"]},
        )
        return str(checkpoint["id"])

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        """The reconciler's re-derivation (TR-D6): the same recorder-less walk the settlement
        folds, over the registered saver, from the result checkpoint back to the source."""

        saver = self._checkpointers.get(checkpointer_ref_digest)
        if saver is None:
            raise TimeTravelUnsupported(
                LANE_PROFILE, reason="checkpointer_not_registered", saver=checkpointer_ref_digest
            )
        with _saver_outcome(checkpointer_ref_digest):
            return await walk_points(
                saver,
                thread=namespace,
                checkpointer_ref_digest=checkpointer_ref_digest,
                source_id=source_locator,
                result_id=result_locator,
                saver_locator_digest=self._locators.get(checkpointer_ref_digest),
            )

    # --- rendering ----------------------------------------------------------------------

    def _message(self, message: BaseMessage, withheld: list[str]) -> StateMessage:
        text = _text(message.content)
        redacted, redactions = redact_text(text) if text else ("", ())
        encoded = redacted.encode("utf-8")
        truncated = len(encoded) > self._cap
        if truncated:
            withheld.append(f"message {message.id or '?'} text excerpted")
        calls: list[ToolCallFact] = []
        usage: dict[str, int] = {}
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                arguments, _found = redact_value(call.get("args"))
                canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
                oversized = len(canonical.encode("utf-8")) > self._cap
                calls.append(
                    ToolCallFact(
                        id=call.get("id"),
                        name=str(call.get("name") or "tool"),
                        arguments=None if oversized else arguments,
                        arguments_digest="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                        arguments_bytes=len(canonical.encode("utf-8")),
                        truncated=oversized,
                    )
                )
            for name, amount in (message.usage_metadata or {}).items():
                if isinstance(amount, int) and not isinstance(amount, bool):
                    usage[f"tokens.{name}"] = amount
        return StateMessage(
            id=message.id,
            role=message.type,
            name=message.name,
            tool_call_id=message.tool_call_id if isinstance(message, ToolMessage) else None,
            tool_calls=tuple(calls),
            text=encoded[: self._cap].decode("utf-8", errors="ignore") if text else None,
            text_bytes=len(encoded),
            text_digest=("sha256:" + hashlib.sha256(encoded).hexdigest()) if text else None,
            truncated=truncated,
            redactions=len(redactions),
            usage=usage,
        )


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") in {"text", None}:
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content) if content is not None else ""


@contextmanager
def _saver_outcome(checkpointer_ref_digest: str) -> Iterator[None]:
    """P6.1: a saver that does not answer is a typed outcome, never a bare driver error."""

    try:
        yield
    except TimeTravelUnsupported:
        raise
    # Tracing Stage 3 (R2-21): only a saver that did not answer (connection, pool timeout,
    # a closed connection) is `saver_unreachable`; a programming or data error is a defect
    # and propagates.
    except (OSError, ConnectionError, psycopg.OperationalError, psycopg.InterfaceError) as error:
        raise TimeTravelUnsupported(
            LANE_PROFILE, reason="saver_unreachable", saver=checkpointer_ref_digest
        ) from error


def _is_snapshot(value: Any) -> bool:
    return isinstance(value, _DeltaSnapshot)


def _snapshot_value(value: Any) -> Any:
    """A stored delta snapshot's value; any other stored channel value as it is."""

    return value.value if isinstance(value, _DeltaSnapshot) else value


async def _message_count(
    saver: BaseCheckpointSaver[Any], thread_id: str, checkpoint_id: str
) -> int | None:
    """Tracing Stage 3 (R2-1): the number of messages a root checkpoint folds to."""

    config = root_checkpoint_config(thread_id, checkpoint_id)
    item = await saver.aget_tuple(config)
    if item is None:
        return None
    stored = (item.checkpoint.get("channel_values") or {}).get("messages")
    if stored is not None:
        value = _snapshot_value(stored)
        return len(value) if isinstance(value, list) else None
    histories = await saver.aget_delta_channel_history(config=config, channels=["messages"])
    folded = fold_delta_history(histories.get("messages") or {})
    return len(folded) if isinstance(folded, list) else None


def _point_config(key: QualifiedCheckpointKey) -> RunnableConfig:
    """The saver config of a root point, or of a sync subagent's nested point."""

    if key.is_root:
        return root_checkpoint_config(key.thread_id, key.checkpoint_id)
    return {
        "configurable": {
            "thread_id": key.thread_id,
            "checkpoint_ns": key.checkpoint_ns,
            "checkpoint_id": key.checkpoint_id,
        }
    }


def _manifest_digest(record: CognitionPointRecord) -> str | None:
    value = record.channel_facts.get("materialization_digest")
    return value if isinstance(value, str) and value.startswith(_DIGEST_PATTERN_PREFIX) else None


def _manifest_digest_of(manifest: Mapping[str, Any]) -> str | None:
    value = manifest.get("digest")
    return value if isinstance(value, str) and value.startswith(_DIGEST_PATTERN_PREFIX) else None


def _uploaded_files(manifest: Mapping[str, Any]) -> list[StateFile]:
    files: list[StateFile] = []
    for entry in manifest.get("files") or ():
        if not isinstance(entry, Mapping) or entry.get("destination") != SOURCE_SANDBOX_UPLOAD:
            continue
        digest = entry.get("digest")
        path = entry.get("path")
        if not isinstance(digest, str) or not isinstance(path, str) or not path:
            continue
        files.append(
            StateFile(
                path=path,
                size_bytes=int(entry.get("bytes") or 0),
                digest=digest,
                source=SOURCE_SANDBOX_UPLOAD,
            )
        )
    files.sort(key=lambda item: item.path)
    return files


def _files(files: Any) -> list[tuple[str, Any]]:
    return list(files.items()) if isinstance(files, Mapping) else []


def _file(path: str, data: Any) -> StateFile:
    content = data.get("content") if isinstance(data, Mapping) else data
    encoding = str(data.get("encoding", "utf-8")) if isinstance(data, Mapping) else "utf-8"
    if isinstance(content, list):
        content = "\n".join(str(line) for line in content)
    payload = (
        base64.standard_b64decode(str(content))
        if encoding != "utf-8" and isinstance(content, str)
        else str(content if content is not None else "").encode("utf-8", errors="replace")
    )
    return StateFile(
        path=str(path),
        size_bytes=len(payload),
        digest="sha256:" + hashlib.sha256(payload).hexdigest(),
        encoding=encoding[:32],
        source=SOURCE_STATE_CHANNEL,
    )


def _bounded(value: Any, cap: int, withheld: list[str], name: str) -> Any:
    redacted, _found = redact_value(jsonable(value))
    canonical = json.dumps(redacted, sort_keys=True, separators=(",", ":"), default=str)
    if len(canonical.encode("utf-8")) > cap:
        withheld.append(f"channel {name} oversized")
        return {
            "withheld": "oversized",
            "bytes": len(canonical.encode("utf-8")),
            "digest": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
    return redacted


def _internal(channel: object) -> bool:
    return not isinstance(channel, str) or channel.startswith(("branch:to:", "__"))


__all__ = [
    "LANE_PROFILE",
    "DeepAgentsTimeTravel",
    "FrameStoreManifestReader",
    "MaterializationManifestReader",
]
