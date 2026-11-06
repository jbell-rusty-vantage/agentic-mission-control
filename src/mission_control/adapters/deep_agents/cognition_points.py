"""Deep Agents cognition points: one observation per root checkpoint of an attempt's lineage.

The lane's side of `mc.cognition_point.v1` (P1 turn 4). After `_capture_result` verified the
stamped root lineage from the result back to the expected source, this module walks it once
more and folds, per checkpoint, the redacted facts the kernel index carries: the step and
source LangGraph stamped, the message identities (the `messages` delta channel folded as
`add_messages` would), the usage the attempt's model calls had consumed up to that point,
the digest of the `files` channel, the allowlisted channel facts, and the provider keys of
the frames recorded while the step ran (from the recorder). It never builds an agent and
never writes: the saver is read by qualified key only. Points are evidence; the transition
and the result stay the only settlement records.

1.4.4 (P3.6, P3.7): with the recorder, the nested checkpoints of every sync subagent the
stream reported (`tools:<task_id>` namespaces) become points too, each naming its subagent
(`subordinate_ref`) and, on the child's first checkpoint, the root point of the step that
spawned it (the one whose frames hold the `task` call); the input point carries the
materialization manifest's digest and the result point the workspace-candidates ref.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.checkpoint.serde.types import _DeltaSnapshot

from mission_control.adapters.deep_agents.checkpoint_reads import (
    checkpoint_parent_id,
    root_checkpoint_config,
)
from mission_control.adapters.deep_agents.frames import DeepAgentFrameRecorder
from mission_control.domain.execution.checkpoint_lineage import (
    ROOT_CHECKPOINT_NS,
    CheckpointCapture,
    CheckpointInvocationPlan,
    CheckpointLineageInDoubt,
)
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionPointObservation,
    PointRole,
    PointSource,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.policies.inspection import summarize_channel_values

MAX_POINT_WALK = 512
# Tracing Stage 3 (R3-F6): the listing bound of one sync subagent's namespace; past it the
# namespace's points are incomplete (named on the result point), never a lineage incident.
MAX_SUBAGENT_POINT_WALK = MAX_POINT_WALK
# 1.4.4 (P6.1): the settlement's points walk budget (wall clock) before the result point
# records `points_status: incomplete` for the reconciler to complete.
DEFAULT_POINTS_WALK_BUDGET_MS = 5_000
_REMOVE_ALL_MESSAGES = "__remove_all__"
_KNOWN_SOURCES: frozenset[str] = frozenset(
    {"input", "loop", "update", "fork", "interrupt", "resume", "compaction"}
)


async def collect_points(
    checkpointer: BaseCheckpointSaver[Any],
    plan: CheckpointInvocationPlan,
    capture: CheckpointCapture,
    *,
    recorder: DeepAgentFrameRecorder | None,
    interrupted_leaf: str | None = None,
    manifest_digest: str | None = None,
    workspace_checkpoint_ref: str | None = None,
    saver_locator_digest: str | None = None,
    budget_seconds: float | None = None,
) -> tuple[CognitionPointObservation, ...]:
    """The attempt's lineage as points, oldest first: result inclusive, source exclusive,
    then (with a recorder) the points of every sync subagent's nested namespace.

    `interrupted_leaf` is the leaf an `interrupt_and_inject` cancelled (FT-F2); it and the
    replacement's first checkpoint get their roles. The source key itself (another unit's
    settled result, or the previous attempt's) is referenced as the first point's parent and
    never re-emitted. With a recorder, each point carries the provider keys of the frames
    recorded while its step ran (the finish frames belong to the result). `manifest_digest`
    (the `environment_materialized` frame's) lands in the first point's
    `channel_facts["materialization_digest"]`; `workspace_checkpoint_ref` on the result point.
    """

    harness_execution = str(recorder.handle.harness_execution_id) if recorder is not None else None
    deadline = time.monotonic() + budget_seconds if budget_seconds is not None else None
    observations = list(
        await walk_points(
            checkpointer,
            thread=plan.namespace,
            checkpointer_ref_digest=plan.checkpointer_ref_digest,
            source_id=(
                capture.source_key.checkpoint_id if capture.source_key is not None else None
            ),
            result_id=capture.result_key.checkpoint_id,
            attempt_ref=plan.attempt_ref,
            native_turn_ref=plan.invocation_id,
            harness_execution_id=harness_execution,
            frame_keys_for=recorder.frame_keys_for if recorder is not None else None,
            pending_keys=recorder.pending_frame_keys() if recorder is not None else (),
            interrupted_leaf=interrupted_leaf,
            saver_locator_digest=saver_locator_digest,
            budget_seconds=budget_seconds,
        )
    )
    if observations and manifest_digest is not None:
        first = observations[0]
        observations[0] = first.model_copy(
            update={
                "channel_facts": {**first.channel_facts, "materialization_digest": manifest_digest}
            }
        )
    if observations and workspace_checkpoint_ref is not None:
        observations[-1] = observations[-1].model_copy(
            update={"workspace_checkpoint_ref": workspace_checkpoint_ref}
        )
    if recorder is not None and observations:
        # Tracing Stage 3 (R2-14, R3-F6): the reconciler re-walks only the root lineage, so
        # the nested namespaces are walked here in what is left of the same budget, and a
        # namespace the budget or the walk bound cut short is named on the result point
        # (`subagent_points: incomplete`, `points_status: incomplete`) instead of failing
        # the settlement or being skipped silently.
        nested, unwalked = await _subagent_points(
            checkpointer,
            plan,
            recorder,
            tuple(observations),
            saver_locator_digest,
            deadline=deadline,
        )
        if unwalked:
            result = observations[-1]
            observations[-1] = result.model_copy(
                update={
                    "channel_facts": {
                        **result.channel_facts,
                        "points_status": "incomplete",
                        "points_walked": result.channel_facts.get(
                            "points_walked", len(observations)
                        ),
                        "subagent_points": "incomplete",
                        "subagent_namespaces_unwalked": list(unwalked),
                    }
                }
            )
        observations.extend(nested)
    return tuple(observations)


def points_incomplete(observation: CognitionPointObservation) -> bool:
    """Whether a result observation records a budget-bounded, partial points walk."""

    return observation.channel_facts.get("points_status") == "incomplete"


async def _subagent_points(
    checkpointer: BaseCheckpointSaver[Any],
    plan: CheckpointInvocationPlan,
    recorder: DeepAgentFrameRecorder,
    roots: tuple[CognitionPointObservation, ...],
    saver_locator_digest: str | None = None,
    *,
    deadline: float | None = None,
) -> tuple[list[CognitionPointObservation], tuple[str, ...]]:
    """One point per nested-namespace checkpoint the recorder observed (P3.6), per subagent,
    and the namespaces the walk could not complete.

    The namespace's checkpoints are listed from the saver in one query (`alist` with the
    `checkpoint_ns` set; the Postgres saver filters `checkpoint_ns = %s`, the in-memory one
    the same) and bounded to the ids the stream reported, oldest first. The child's first
    checkpoint links to the root point whose frames hold the spawning `task` call
    (`parent_locator`) and carries `subagent_root`; the rest link to their own parent.

    Tracing Stage 3 (R3-F6): the walk degrades like the root walk. A namespace longer than
    `MAX_SUBAGENT_POINT_WALK` keeps the checkpoints found within the bound, and once
    `deadline` passes the remaining namespaces are not walked; either way the namespace is
    reported unwalked, never raised as a lineage incident over a completed turn.
    """

    points: list[CognitionPointObservation] = []
    unwalked: list[str] = []
    harness_execution = str(recorder.handle.harness_execution_id)
    for namespace in recorder.nested_namespaces():
        observed = recorder.observed_checkpoints(ns=namespace)
        if not observed:
            continue
        if deadline is not None and time.monotonic() > deadline:
            unwalked.append(namespace)
            continue
        config: RunnableConfig = {
            "configurable": {"thread_id": plan.namespace, "checkpoint_ns": namespace}
        }
        found: dict[str, CheckpointTuple] = {}
        listed = 0
        async for item in checkpointer.alist(config):
            listed += 1
            if listed > MAX_SUBAGENT_POINT_WALK or (
                deadline is not None and time.monotonic() > deadline
            ):
                break
            checkpoint_id = str(item.config["configurable"]["checkpoint_id"])
            if checkpoint_id in observed:
                found[checkpoint_id] = item
            if len(found) == len(observed):
                break
        if len(found) < len(observed):
            unwalked.append(namespace)
        items = [found[checkpoint_id] for checkpoint_id in observed if checkpoint_id in found]
        if not items:
            continue
        spawn = _spawning_root(recorder, namespace, roots)
        name = recorder.agent_name(namespace)
        pending = recorder.pending_frame_keys(ns=namespace)
        previous_usage: dict[str, int] = {}
        for index, item in enumerate(items):
            checkpoint_id = str(item.config["configurable"]["checkpoint_id"])
            parent_id = checkpoint_parent_id(item)
            metadata = dict(item.metadata or {})
            step = metadata.get("step")
            source = metadata.get("source")
            last = index == len(items) - 1
            roles: list[PointRole] = []
            if source == "input":
                roles.append("input")
            if index == 0:
                roles.append("subagent_root")
            if last:
                roles.append("leaf")
            elif "input" not in roles:
                roles.append("intermediate")
            values, messages = await _state_at(
                checkpointer, plan.namespace, checkpoint_id, item, ns=namespace
            )
            usage = _usage_of(messages)
            facts = summarize_channel_values(values)
            frame_keys = recorder.frame_keys_for(checkpoint_id, ns=namespace)
            if last:
                frame_keys = (*frame_keys, *pending)
            points.append(
                CognitionPointObservation(
                    point=CheckpointPoint(
                        key=QualifiedCheckpointKey(
                            checkpointer_ref_digest=plan.checkpointer_ref_digest,
                            thread_id=plan.namespace,
                            checkpoint_ns=namespace,
                            checkpoint_id=checkpoint_id,
                            parent_checkpoint_id=parent_id,
                            saver_locator_digest=saver_locator_digest,
                        ),
                        subordinate_ref=name,
                    ),
                    # Tracing Stage 3 (R1-F7): a parent the bounded walk did not fold is
                    # still named; only the child's root links to the spawning point.
                    parent_locator=parent_id if parent_id is not None else spawn,
                    ordinal=step if isinstance(step, int) else None,
                    source=cast(PointSource, source) if source in _KNOWN_SOURCES else None,
                    roles=tuple(roles),
                    attempt_ref=plan.attempt_ref,
                    harness_execution_id=harness_execution,
                    native_turn_ref=plan.invocation_id,
                    frame_keys=tuple(frame_keys),
                    message_count=len(messages),
                    channel_facts=facts.model_dump(mode="json"),
                    files_digest=_files_digest(values.get("files")),
                    usage_delta=_delta(previous_usage, usage),
                    seedable=False,
                    native_observed_at=_checkpoint_ts(item),
                )
            )
            previous_usage = usage
    return points, tuple(unwalked)


def _spawning_root(
    recorder: DeepAgentFrameRecorder,
    namespace: str,
    roots: tuple[CognitionPointObservation, ...],
) -> str | None:
    """The root checkpoint whose frame keys hold the `task` call that spawned the child (the
    result point's keys already include the pending finish window)."""

    call_id = recorder.task_call_for(namespace)
    started_key = recorder.task_started_key(call_id) if call_id is not None else None
    if started_key is None:
        return None
    for point in roots:
        if started_key in point.frame_keys:
            return point.locator
    return None


async def walk_points(
    checkpointer: BaseCheckpointSaver[Any],
    *,
    thread: str,
    checkpointer_ref_digest: str,
    source_id: str | None,
    result_id: str,
    attempt_ref: str | None = None,
    native_turn_ref: str | None = None,
    harness_execution_id: str | None = None,
    frame_keys_for: Callable[[str], tuple[str, ...]] | None = None,
    pending_keys: tuple[str, ...] = (),
    interrupted_leaf: str | None = None,
    saver_locator_digest: str | None = None,
    budget_seconds: float | None = None,
) -> tuple[CognitionPointObservation, ...]:
    """The recorder-less walk: the root lineage of `thread` from `result_id` back to (and
    excluding) `source_id`, folded into one observation per checkpoint, oldest first.

    This is what the reconciler re-derives through `TimeTravelLane.collect_points` after a
    settlement lost its point rows: the saver is read by qualified key only, nothing is
    written, and the facts are the same ones the settlement would have folded.

    1.4.4 (P6.1): with `budget_seconds` the walk stops when the budget is spent (the result
    checkpoint is always folded) and the result observation records
    `channel_facts.points_status == "incomplete"` with `points_walked`; the settlement
    proceeds and the reconciler completes the points later. `saver_locator_digest` names the
    saver on every key.
    """

    deadline = time.monotonic() + budget_seconds if budget_seconds is not None else None
    items: list[CheckpointTuple] = []
    cursor: str | None = result_id
    exhausted = False
    while cursor is not None and cursor != source_id:
        if len(items) >= MAX_POINT_WALK:
            raise CheckpointLineageInDoubt(
                "the lineage is longer than the point walk bound", reason="unclassifiable"
            )
        if deadline is not None and items and time.monotonic() > deadline:
            exhausted = True
            break
        item = await checkpointer.aget_tuple(root_checkpoint_config(thread, cursor))
        if item is None:
            raise CheckpointLineageInDoubt(
                "a checkpoint of the result lineage is missing", reason="missing_checkpoint"
            )
        items.append(item)
        cursor = checkpoint_parent_id(item)
    items.reverse()
    walked = {str(item.config["configurable"]["checkpoint_id"]) for item in items}
    source_point = (
        CheckpointPoint(
            key=QualifiedCheckpointKey(
                checkpointer_ref_digest=checkpointer_ref_digest,
                thread_id=thread,
                checkpoint_ns=ROOT_CHECKPOINT_NS,
                checkpoint_id=source_id,
                saver_locator_digest=saver_locator_digest,
            )
        )
        if source_id is not None
        else None
    )
    observations: list[CognitionPointObservation] = []
    # Tracing Stage 3 (R2-14): the first folded point's usage delta is measured from its own
    # parent (the source on a complete walk, the first unwalked checkpoint on a walk the
    # budget cut short), never from zero, which would charge it the thread's whole usage.
    first_parent = checkpoint_parent_id(items[0]) if items else None
    previous_usage: dict[str, int] = (
        await _usage_at(checkpointer, thread, first_parent) if first_parent is not None else {}
    )
    replacement_next = False
    for index, item in enumerate(items):
        checkpoint_id = str(item.config["configurable"]["checkpoint_id"])
        parent_id = checkpoint_parent_id(item)
        metadata = dict(item.metadata or {})
        step = metadata.get("step")
        source = metadata.get("source")
        last = index == len(items) - 1
        roles: list[PointRole] = []
        if source == "input":
            roles.append("input")
        if last:
            roles.extend(("leaf", "result"))
        elif "input" not in roles:
            roles.append("intermediate")
        if interrupted_leaf is not None and checkpoint_id == interrupted_leaf:
            roles.append("interrupted")
            replacement_next = True
        elif replacement_next:
            roles.append("replacement_start")
            replacement_next = False
        values, messages = await _state_at(checkpointer, thread, checkpoint_id, item)
        usage = _usage_of(messages)
        facts = summarize_channel_values(values)
        frame_keys = frame_keys_for(checkpoint_id) if frame_keys_for is not None else ()
        if last:
            frame_keys = (*frame_keys, *pending_keys)
        observations.append(
            CognitionPointObservation(
                point=CheckpointPoint(
                    key=QualifiedCheckpointKey(
                        checkpointer_ref_digest=checkpointer_ref_digest,
                        thread_id=thread,
                        checkpoint_ns=ROOT_CHECKPOINT_NS,
                        checkpoint_id=checkpoint_id,
                        parent_checkpoint_id=parent_id,
                        saver_locator_digest=saver_locator_digest,
                    )
                ),
                # Tracing Stage 3 (R1-F7): a parent the budget left unwalked is still named
                # (its checkpoint id), so the settlement never infers a cross-cycle parent
                # from its absence; only the source is referenced as a point outside.
                parent_locator=(
                    parent_id if parent_id is not None and parent_id != source_id else None
                ),
                parent_point=(
                    source_point
                    if parent_id is not None and parent_id not in walked and parent_id == source_id
                    else None
                ),
                ordinal=step if isinstance(step, int) else None,
                source=cast(PointSource, source) if source in _KNOWN_SOURCES else None,
                roles=tuple(roles),
                attempt_ref=attempt_ref,
                harness_execution_id=harness_execution_id,
                native_turn_ref=native_turn_ref,
                frame_keys=tuple(frame_keys),
                message_count=len(messages),
                channel_facts=facts.model_dump(mode="json"),
                files_digest=_files_digest(values.get("files")),
                usage_delta=_delta(previous_usage, usage),
                seedable=True,
                native_observed_at=_checkpoint_ts(item),
            )
        )
        previous_usage = usage
        if deadline is not None and time.monotonic() > deadline and not last:
            # The budget ran out while folding: keep what is folded, the result last.
            exhausted = True
            remaining = items[index + 1 :]
            if remaining:
                items = [*items[: index + 1], items[-1]]
                observations.append(
                    await _fold_result_only(
                        checkpointer,
                        thread,
                        checkpointer_ref_digest,
                        items[-1],
                        source_point=source_point,
                        attempt_ref=attempt_ref,
                        native_turn_ref=native_turn_ref,
                        harness_execution_id=harness_execution_id,
                        frame_keys_for=frame_keys_for,
                        pending_keys=pending_keys,
                        saver_locator_digest=saver_locator_digest,
                    )
                )
            break
    if exhausted and observations:
        result = observations[-1]
        observations[-1] = result.model_copy(
            update={
                "channel_facts": {
                    **result.channel_facts,
                    "points_status": "incomplete",
                    "points_walked": len(observations),
                }
            }
        )
    return tuple(observations)


async def _fold_result_only(
    checkpointer: BaseCheckpointSaver[Any],
    thread: str,
    checkpointer_ref_digest: str,
    item: CheckpointTuple,
    *,
    source_point: CheckpointPoint | None,
    attempt_ref: str | None,
    native_turn_ref: str | None,
    harness_execution_id: str | None,
    frame_keys_for: Callable[[str], tuple[str, ...]] | None,
    pending_keys: tuple[str, ...],
    saver_locator_digest: str | None,
) -> CognitionPointObservation:
    """The result observation alone (P6.1): folded after the budget ran out so the
    settlement still names its result point; its usage delta is left empty. Tracing Stage 3
    (R1-F7): its parent is named by checkpoint id although the walk did not fold it (or as
    the source point when it is the source)."""

    checkpoint_id = str(item.config["configurable"]["checkpoint_id"])
    parent_id = checkpoint_parent_id(item)
    metadata = dict(item.metadata or {})
    step = metadata.get("step")
    source = metadata.get("source")
    values, messages = await _state_at(checkpointer, thread, checkpoint_id, item)
    facts = summarize_channel_values(values)
    frame_keys = frame_keys_for(checkpoint_id) if frame_keys_for is not None else ()
    return CognitionPointObservation(
        point=CheckpointPoint(
            key=QualifiedCheckpointKey(
                checkpointer_ref_digest=checkpointer_ref_digest,
                thread_id=thread,
                checkpoint_ns=ROOT_CHECKPOINT_NS,
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=parent_id,
                saver_locator_digest=saver_locator_digest,
            )
        ),
        parent_locator=(
            parent_id
            if parent_id is not None
            and (source_point is None or parent_id != source_point.key.checkpoint_id)
            else None
        ),
        parent_point=(
            source_point
            if source_point is not None and parent_id == source_point.key.checkpoint_id
            else None
        ),
        ordinal=step if isinstance(step, int) else None,
        source=cast(PointSource, source) if source in _KNOWN_SOURCES else None,
        roles=("leaf", "result"),
        attempt_ref=attempt_ref,
        harness_execution_id=harness_execution_id,
        native_turn_ref=native_turn_ref,
        frame_keys=(*frame_keys, *pending_keys),
        message_count=len(messages),
        channel_facts=facts.model_dump(mode="json"),
        files_digest=_files_digest(values.get("files")),
        usage_delta={},
        seedable=True,
        native_observed_at=_checkpoint_ts(item),
    )


def _checkpoint_ts(item: CheckpointTuple) -> datetime | None:
    """The checkpoint's own `ts` (ISO 8601 with offset), the worker's clock at creation."""

    value = item.checkpoint.get("ts") if isinstance(item.checkpoint, Mapping) else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _checkpoint_config(thread: str, ns: str, checkpoint_id: str) -> RunnableConfig:
    if ns == ROOT_CHECKPOINT_NS:
        return root_checkpoint_config(thread, checkpoint_id)
    return {
        "configurable": {"thread_id": thread, "checkpoint_ns": ns, "checkpoint_id": checkpoint_id}
    }


async def _state_at(
    checkpointer: BaseCheckpointSaver[Any],
    thread: str,
    checkpoint_id: str,
    item: CheckpointTuple,
    *,
    ns: str = ROOT_CHECKPOINT_NS,
) -> tuple[dict[str, Any], list[Any]]:
    """The checkpoint's state channels (delta channels folded) and its message objects."""

    stored = item.checkpoint.get("channel_values") or {}
    # Tracing Stage 3 (R2-1 follow-up): a delta channel stores a full `_DeltaSnapshot` every
    # 50 updates; at such a checkpoint the stored value is the snapshot, not the list.
    values: dict[str, Any] = {
        name: value.value if isinstance(value, _DeltaSnapshot) else value
        for name, value in stored.items()
        if not _internal(name)
    }
    delta_channels = [
        name
        for name in item.checkpoint.get("channel_versions") or {}
        if not _internal(name) and name not in values
    ]
    messages: list[Any] = []
    if isinstance(values.get("messages"), list):
        messages = list(values["messages"])
    if delta_channels:
        histories = await checkpointer.aget_delta_channel_history(
            config=_checkpoint_config(thread, ns, checkpoint_id), channels=delta_channels
        )
        for name, history in histories.items():
            folded = fold_delta_history(history)
            values[name] = folded
            if name == "messages" and isinstance(folded, list):
                messages = folded
    return values, messages


async def _usage_at(
    checkpointer: BaseCheckpointSaver[Any], thread: str, checkpoint_id: str
) -> dict[str, int]:
    item = await checkpointer.aget_tuple(root_checkpoint_config(thread, checkpoint_id))
    if item is None:
        return {}
    _values, messages = await _state_at(checkpointer, thread, checkpoint_id, item)
    return _usage_of(messages)


def fold_delta_history(history: Mapping[str, Any]) -> Any:
    """Fold a delta channel's seed and writes into its value (messages by identity)."""

    seed = history.get("seed")
    seed = getattr(seed, "value", seed)
    writes = [write[2] for write in history.get("writes", ())]
    if isinstance(seed, Mapping) or (seed is None and writes and isinstance(writes[0], Mapping)):
        merged: dict[str, Any] = dict(seed or {})
        for update in writes:
            if isinstance(update, Mapping):
                for name, value in update.items():
                    if value is None:
                        merged.pop(str(name), None)
                    else:
                        merged[str(name)] = value
        return merged
    ordered: dict[str, Any] = {}
    anonymous = 0

    def apply(message: Any) -> None:
        nonlocal anonymous
        identity = getattr(message, "id", None)
        if identity is None and isinstance(message, Mapping):
            identity = message.get("id")
        if getattr(message, "type", None) == "remove":
            if identity == _REMOVE_ALL_MESSAGES:
                ordered.clear()
            else:
                ordered.pop(str(identity), None)
            return
        if identity is None:
            anonymous += 1
            identity = f"anonymous:{anonymous}"
        ordered[str(identity)] = message

    for message in seed if isinstance(seed, list | tuple) else ():
        apply(message)
    for update in writes:
        for message in update if isinstance(update, list | tuple) else (update,):
            apply(message)
    return list(ordered.values())


def _usage_of(messages: list[Any]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for message in messages:
        if isinstance(message, AIMessage) and message.usage_metadata:
            for key, value in message.usage_metadata.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[f"tokens.{key}"] = totals.get(f"tokens.{key}", 0) + value
    return totals


def _delta(previous: Mapping[str, int], current: Mapping[str, int]) -> dict[str, int]:
    return {
        key: current.get(key, 0) - previous.get(key, 0)
        for key in sorted(set(previous) | set(current))
        if current.get(key, 0) - previous.get(key, 0) != 0
    }


def _files_digest(files: Any) -> str | None:
    """A digest over the `files` channel (StateBackend): path -> content digest, sorted."""

    if not isinstance(files, Mapping) or not files:
        return None
    manifest: dict[str, str] = {}
    for path in sorted(files):
        data = files[path]
        content = data.get("content") if isinstance(data, Mapping) else data
        if isinstance(content, list):
            content = "\n".join(str(line) for line in content)
        payload = str(content).encode("utf-8", errors="replace")
        manifest[str(path)] = hashlib.sha256(payload).hexdigest()
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _internal(channel: object) -> bool:
    return not isinstance(channel, str) or channel.startswith(("branch:to:", "__"))


# OVE-204 slice 5: the Workspace Closure keeps this text digest as its cross-check.
files_channel_digest = _files_digest


__all__ = [
    "MAX_POINT_WALK",
    "collect_points",
    "files_channel_digest",
    "fold_delta_history",
    "walk_points",
]
