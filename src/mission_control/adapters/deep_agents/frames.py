"""Deep Agents frame writer: LangGraph `astream` v2 parts -> provider frames (SPEC-03, C1).

One `DeepAgentFrameRecorder` serves one invocation (one turn) of one harness execution.
It consumes `astream(..., stream_mode=["updates", "messages", "custom", "checkpoints"],
subgraphs=True, version="v2")` parts and persists, in arrival order and before anything is
derived:

- `session_init` and `turn_started` before the first model call, then (1.4.4, P3.7) the one
  `environment_materialized` frame: the materialization manifest the adapter assembles from
  the materializer's facts and the context files it seeded;
- `model_request` (1.4.4, P3.4) for every chat-model call, captured at the chat-model
  boundary by the adapter's `_ModelRequestObserver` and queued here; the queue is drained on
  the event loop before the next part is written, so the request frame's arrival ordinal
  precedes the response frames of its call;
- `message_delta` / `thinking_delta` coalesced from `messages`-mode chunks (bounded, never
  one row per token) and `message` for each completed AI message in `updates`;
- `tool_call_started` for each tool call an AI message requests and `tool_call_completed`
  / `tool_call_failed` for each `ToolMessage` (keyed by `tool_call_id`);
- `subagent_started` beside the `task` tool call and `subagent_ended` (closing) beside its
  tool message (1.4.4, P3.6), the latter with the usage summed from the child's `message`
  frames observed under its namespace;
- `usage` (closing) for each AI message that reports provider token usage;
- `approval_requested` for a LangGraph interrupt, `after_compaction` for a
  `_summarization_event`, and the Mission Control custom events (`mc.before_compaction`,
  `mc.after_compaction`, `mc.hook_invoked`, `mc.hook_result`, `mc.approval_resolved`)
  that middleware writes through the stream writer;
- `turn_ended` and `run_result` when the invocation finishes, or `error` / `run_result
  {error}` when it fails, plus `tool_call_completed` backfill (`raw_kind =
  "checkpoint_backfill"`) for any tool result the stream did not deliver.

Subagent frames (namespace `tools:<task_id>`) carry `subordinate_ref` from
`metadata.lc_agent_name`, the `task` call's `subagent_type`, or the namespace. The dedupe
key is `thread_id:checkpoint_ns:checkpoint_id:step:<message_id|tool_call_id>:<kind>`; the
checkpoint slot names the **last root checkpoint the recorder had seen** when it observed
the frame (P4.2 `after_point_ref`; empty before the first), the finish frames name the
result checkpoint, and message ids and tool call ids are the stable discriminators, so
re-running the writer over the same stream (or reconstructing a terminal run) adds no rows.

`checkpoints` parts close the pending frame window of their namespace: root checkpoints
become the attempt's points, nested-namespace checkpoints become a subagent's points
(`cognition_points.collect_points`), each with the keys of the frames recorded while its
step ran.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

from mission_control.adapters.deep_agents.budget import turn_stop_marker
from mission_control.application.frames.kinds import (
    UNKNOWN_KINDS,
    UnknownKindCounter,
    classify,
    deep_agents_key,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.body import FrameBody, batch_frame_body, frame_body, jsonable
from mission_control.domain.frames.contracts import (
    DEFAULT_EXCERPT_CAP_BYTES,
    AppendReceipt,
    FrameKind,
    FrameObservation,
    HarnessExecutionHandle,
    LaneProfile,
)

logger = logging.getLogger(__name__)

LANE = LaneProfile.DEEP_AGENTS
DELTA_FLUSH_BYTES = 2_048
NS_SEP = "|"
TASK_TOOL = "task"
MODEL_REQUEST_RAW_KIND = "model.request"
MANIFEST_RAW_KIND = "materialization.manifest"
SOURCE_STATE_CHANNEL = "state_channel"
SOURCE_SANDBOX_UPLOAD = "sandbox_upload"
_THINKING_BLOCKS = {"reasoning", "thinking"}
_OBJECT_MESSAGE_TYPES = {"human", "system"}
_JSON = "application/json"


def _digest(value: Any) -> str:
    payload = json.dumps(jsonable(value), sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or ():
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, Mapping) and block.get("type") not in _THINKING_BLOCKS:
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _thinking(message: BaseMessage) -> str:
    parts: list[str] = []
    content = message.content
    if not isinstance(content, str):
        for block in content or ():
            if isinstance(block, Mapping) and block.get("type") in _THINKING_BLOCKS:
                for key in ("reasoning", "thinking", "text"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
    extra = message.additional_kwargs.get("reasoning_content")
    if isinstance(extra, str):
        parts.append(extra)
    return "".join(parts)


def usage_counts(metadata: Mapping[str, Any] | None) -> dict[str, int]:
    """The provider-reported token counts of one message, as every usage body records them."""

    if not metadata:
        return {}
    counts = {
        "input_tokens": int(metadata.get("input_tokens", 0) or 0),
        "output_tokens": int(metadata.get("output_tokens", 0) or 0),
        "total_tokens": int(metadata.get("total_tokens", 0) or 0),
    }
    details = metadata.get("input_token_details") or {}
    if isinstance(details, Mapping) and details.get("cache_read") is not None:
        counts["cached_input_tokens"] = int(details.get("cache_read") or 0)
    output_details = metadata.get("output_token_details") or {}
    if isinstance(output_details, Mapping) and output_details.get("reasoning") is not None:
        counts["reasoning_tokens"] = int(output_details.get("reasoning") or 0)
    return counts


def message_body(message: BaseMessage) -> dict[str, Any]:
    """A JSON body for one LangChain message (content, tool calls, status, usage)."""

    body: dict[str, Any] = {
        "type": message.type,
        "id": message.id,
        "name": message.name,
        "content": jsonable(message.content),
    }
    if isinstance(message, AIMessage):
        body["tool_calls"] = [
            {"id": call.get("id"), "name": call.get("name"), "args": jsonable(call.get("args"))}
            for call in message.tool_calls
        ]
        if message.usage_metadata:
            body["usage"] = usage_counts(message.usage_metadata)
        metadata = message.response_metadata or {}
        for key in ("model_name", "model", "finish_reason", "stop_reason"):
            if key in metadata:
                body[key] = jsonable(metadata[key])
        # Tracing Stage 3 (R3-F9): a turn stop Mission Control answered instead of the model
        # keeps its marker, so a reader can tell it from a model answer.
        marker = turn_stop_marker(message)
        if marker is not None:
            body["mc_stop"] = {
                "marker": marker,
                "detail": jsonable(message.additional_kwargs.get(marker)),
            }
    if isinstance(message, ToolMessage):
        body["tool_call_id"] = message.tool_call_id
        body["status"] = message.status
    return body


def frame_message_body(message: BaseMessage) -> dict[str, Any]:
    """The body a whole message's frame carries: `message_body`, plus the `result_digest` an
    `updates.tool_message` frame records for a tool result. A `model_request` lists the
    batch's messages by the digest of exactly this body, so a replay (P4.3) joins each AI or
    tool entry to its `message` / tool-result frame and each human or system entry to its
    promoted object."""

    body = message_body(message)
    if isinstance(message, ToolMessage):
        body["result_digest"] = _digest(message.content)
    return body


# --- the materialization manifest (P3.7) ------------------------------------------------


@dataclass(frozen=True)
class ManifestFile:
    """One file the adapter seeded before the first model call."""

    path: str
    slot: str | None
    content: bytes
    destination: str  # SOURCE_STATE_CHANNEL | SOURCE_SANDBOX_UPLOAD


def materialization_manifest(
    facts: Mapping[str, Any], context_files: Sequence[ManifestFile] = ()
) -> dict[str, Any]:
    """The `environment_materialized` body: every file the attempt's backend holds before the
    first model call (`{path, slot, bytes, digest, destination}`), the Skill mounts, the MCP
    servers connected and the model resolved, from the materializer's `manifest_facts`
    (`skills`, `mcp_servers`, `model`, `state_files`) plus the context files the adapter
    seeded; `digest` is the sha256 of the canonical body without it."""

    files: list[dict[str, Any]] = [
        {
            "path": item.path,
            "slot": item.slot,
            "bytes": len(item.content),
            "digest": "sha256:" + hashlib.sha256(item.content).hexdigest(),
            "destination": item.destination,
        }
        for item in context_files
    ]
    for entry in facts.get("state_files") or ():
        if not isinstance(entry, Mapping):
            continue
        files.append(
            {
                "path": str(entry.get("path")),
                "slot": entry.get("slot"),
                "bytes": int(entry.get("bytes") or 0),
                "digest": entry.get("digest"),
                "destination": str(entry.get("destination") or SOURCE_STATE_CHANNEL),
            }
        )
    files.sort(key=lambda item: (str(item["path"]), str(item["destination"])))
    body: dict[str, Any] = {
        "files": files,
        "skills": jsonable(list(facts.get("skills") or ())),
        "mcp_servers": jsonable(list(facts.get("mcp_servers") or ())),
        "model": jsonable(dict(facts.get("model") or {})),
    }
    body["digest"] = _digest(body)
    return body


# --- the model-input record (P3.4) --------------------------------------------------------


@dataclass(frozen=True)
class ModelRequestCapture:
    """What the chat-model callback hands the recorder: the `model_request` body without the
    object references, the human/system message objects to promote (canonical bytes by
    digest), the whole batch when the profile keeps it, and the call's key facts."""

    ns: tuple[str, ...]
    step: int | None
    call_index: int
    body: dict[str, Any]
    objects: Mapping[str, bytes]
    batch: tuple[str, bytes] | None


def _tool_entries(tools: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for tool in tools if isinstance(tools, list | tuple) else ():
        name: Any = None
        if isinstance(tool, Mapping):
            function = tool.get("function")
            name = tool.get("name") or (
                function.get("name") if isinstance(function, Mapping) else None
            )
        entries.append({"name": str(name) if name else None, "schema_digest": _digest(tool)})
    return entries


def model_request_capture(
    batch: Sequence[BaseMessage],
    *,
    ns: Sequence[str],
    step: int | None,
    node: str | None,
    checkpoint_ns: str,
    invocation_params: Mapping[str, Any],
    metadata: Mapping[str, Any],
    call_index: int,
    follow_up: bool,
    full_requests: bool,
    secret_values: Iterable[str] = (),
) -> ModelRequestCapture:
    """The P1.1 `model_request` body for one chat-model call: `[system_message, *messages]`
    listed by id, type and body digest (`frame_message_body`, redacted exactly as the frame
    writer redacts), the tools and tool choice bound, the model and the digest of its
    invocation parameters, the LangGraph step facts, and the digest of the whole batch."""

    secrets = tuple(secret_values)
    message_bodies = [frame_message_body(message) for message in batch]
    bodies: list[FrameBody] = [frame_body(raw, secret_values=secrets) for raw in message_bodies]
    system: dict[str, Any] | None = None
    entries: list[dict[str, Any]] = []
    objects: dict[str, bytes] = {}
    for index, (message, body) in enumerate(zip(batch, bodies, strict=True)):
        if message.type in _OBJECT_MESSAGE_TYPES:
            objects.setdefault(body.digest, body.canonical)
        if index == 0 and message.type == "system":
            system = {"digest": body.digest, "bytes": body.body_bytes}
            continue
        entries.append(
            {
                "id": message.id,
                "type": message.type,
                "digest": body.digest,
                "bytes": body.body_bytes,
            }
        )
    # The one batch-digest rule, shared with the replay (`domain/frames/body.py`); the replay
    # compares every request's `batch_digest`, so it is computed under every profile.
    whole = batch_frame_body(message_bodies, secret_values=secrets)
    params = jsonable(dict(invocation_params))
    name = (
        metadata.get("ls_model_name")
        or invocation_params.get("model_name")
        or invocation_params.get("model")
    )
    provider = metadata.get("ls_provider") or invocation_params.get("_type")
    request_body: dict[str, Any] = {
        "langgraph": {"step": step, "node": node, "checkpoint_ns": checkpoint_ns},
        "model": {
            "name": str(name) if name else None,
            "provider": str(provider) if provider else None,
            "invocation_params_digest": _digest(params),
        },
        "system": system,
        "messages": entries,
        "tools": _tool_entries(invocation_params.get("tools")),
        "tool_choice": jsonable(invocation_params.get("tool_choice")),
        "follow_up": follow_up,
        "batch_digest": whole.digest,
        "batch_bytes": whole.body_bytes,
        "call_index": call_index,
    }
    return ModelRequestCapture(
        ns=tuple(ns),
        step=step,
        call_index=call_index,
        body=request_body,
        objects=objects,
        batch=(whole.digest, whole.canonical) if full_requests else None,
    )


class DeepAgentFrameRecorder:
    """Observes one Deep Agents invocation and appends its frames through a FrameWriter."""

    def __init__(
        self,
        writer: FrameWriter,
        *,
        thread_id: str,
        invocation_id: str,
        counter: UnknownKindCounter = UNKNOWN_KINDS,
        delta_flush_bytes: int = DELTA_FLUSH_BYTES,
        secret_values: Iterable[str] = (),
        excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
    ) -> None:
        self._writer = writer
        self._thread = thread_id
        self._turn = invocation_id
        self._counter = counter
        self._flush_bytes = delta_flush_bytes
        self._secrets = tuple(secret_values)
        self._cap = excerpt_cap_bytes
        self._agent_names: dict[str, str] = {}
        self._deltas: dict[tuple[str, str, str], list[Any]] = {}
        self._delta_counts: dict[tuple[str, str, str], int] = {}
        self._closed_tool_calls: set[str] = set()
        self._started_tool_calls: set[str] = set()
        self.unknown = 0
        # P1 turn 4 (`mc.cognition_point.v1`): the frames recorded since the last checkpoint
        # of a namespace belong to the next checkpoint LangGraph emits there (`stream_mode=
        # "checkpoints"`), keyed by `(namespace, checkpoint id)`; what is still pending at
        # `finish` belongs to the result checkpoint (root) or the child's last one (nested).
        # The last root checkpoint seen is the `after_point_ref` slot of every later key.
        self._last_root: str | None = None
        self._pending: dict[str, list[str]] = {"": []}
        self._keys_by_checkpoint: dict[tuple[str, str], tuple[str, ...]] = {}
        self._checkpoint_steps: dict[tuple[str, str], int | None] = {}
        self._checkpoint_order: dict[str, list[str]] = {"": []}
        self._namespaces: list[str] = []
        # 1.4.4 (P3.6): sync subagents spawned through the `task` tool, by tool call id, and
        # the nested namespace (`tools:<task_id>`) each one ran in once it appeared.
        self._task_names: dict[str, str] = {}
        self._ended_tasks: set[str] = set()
        self._task_namespace: dict[str, str] = {}
        self._namespace_task: dict[str, str] = {}
        self._task_started_keys: dict[str, str] = {}
        self._usage_by_namespace: dict[str, dict[str, int]] = {}
        # 1.4.4 (P3.4): model requests captured at the chat-model boundary, drained before
        # the next part is written.
        self._model_requests: list[ModelRequestCapture] = []
        self._object_refs: dict[str, str | None] = {}

    # --- what the collector reads ------------------------------------------------------

    def frame_keys_for(self, checkpoint_id: str, ns: str = "") -> tuple[str, ...]:
        """Provider keys of the frames recorded while the checkpoint's step ran."""

        return self._keys_by_checkpoint.get((ns, checkpoint_id), ())

    def pending_frame_keys(self, ns: str = "") -> tuple[str, ...]:
        """Provider keys recorded after the namespace's last observed checkpoint (for the
        root namespace: the finish frames, which belong to the result point)."""

        return tuple(self._pending.get(ns, ()))

    def observed_checkpoints(self, ns: str = "") -> dict[str, int | None]:
        """Checkpoint ids the stream reported for the namespace, in order, with their steps."""

        return {
            checkpoint_id: self._checkpoint_steps.get((ns, checkpoint_id))
            for checkpoint_id in self._checkpoint_order.get(ns, ())
        }

    def nested_namespaces(self) -> tuple[str, ...]:
        """The `tools:<task_id>` namespaces (joined by `|`) the stream reported, in order."""

        return tuple(self._namespaces)

    def agent_name(self, ns: str) -> str:
        """The subagent a nested namespace belongs to (its `lc_agent_name`, the `task` call's
        `subagent_type`, or the namespace itself)."""

        return self._subordinate(tuple(ns.split(NS_SEP))) or ns

    def task_call_for(self, ns: str) -> str | None:
        """The `task` tool call id that spawned the subagent running in the namespace."""

        root = ns.split(NS_SEP, maxsplit=1)[0]
        return self._namespace_task.get(root)

    def bind_task_namespace(self, call_id: str, checkpoint_ns: str) -> None:
        """Bind a root `task` call to the namespace its child runs in (Tracing Stage 3, R3-F5).

        The adapter's tool callback reports the `tool_call_id` and the LangGraph task
        namespace (`tools:<task_id>`, one `Send` per tool call) when the tool starts; that
        task namespace is the child's stream namespace. Parallel `task` calls run
        concurrently, so the order in which their namespaces first appear in the stream says
        nothing about which call spawned which child.
        """

        segments = checkpoint_ns.split(NS_SEP)
        if len(segments) != 1 or not segments[0].startswith("tools:"):
            return  # a nested child's own `task` call is not a root spawn
        self._task_namespace.setdefault(call_id, segments[0])
        self._namespace_task.setdefault(segments[0], call_id)

    def task_started_key(self, call_id: str) -> str | None:
        """The `tool_call_started` key of a `task` call (the key of the spawning step)."""

        return self._task_started_keys.get(call_id)

    @property
    def full_requests(self) -> bool:
        """Whether the writer's capture profile keeps the whole batch of a model request."""

        capture = getattr(self._writer, "capture", None)
        return bool(capture is not None and capture.full_requests)

    def observe_checkpoint(self, part: Mapping[str, Any]) -> None:
        """A `checkpoints` stream part: close the namespace's pending frame window on it."""

        data = part.get("data")
        if not isinstance(data, Mapping):
            return
        config = data.get("config") or {}
        configurable = config.get("configurable", {}) if isinstance(config, Mapping) else {}
        checkpoint_id = configurable.get("checkpoint_id")
        if not checkpoint_id:
            return
        ns = tuple(str(item) for item in part.get("ns", ()) or ())
        namespace = NS_SEP.join(ns) or str(configurable.get("checkpoint_ns") or "")
        if namespace:
            self._note_namespace(ns or tuple(namespace.split(NS_SEP)))
        metadata = data.get("metadata") or {}
        step = metadata.get("step") if isinstance(metadata, Mapping) else None
        key = (namespace, str(checkpoint_id))
        self._checkpoint_steps[key] = step if isinstance(step, int) else None
        order = self._checkpoint_order.setdefault(namespace, [])
        if str(checkpoint_id) not in order:
            order.append(str(checkpoint_id))
        self._keys_by_checkpoint[key] = tuple(self._pending.get(namespace, ()))
        self._pending[namespace] = []
        if not namespace:
            self._last_root = str(checkpoint_id)

    @property
    def receipt(self) -> AppendReceipt:
        return self._writer.receipt

    @property
    def handle(self) -> HarnessExecutionHandle:
        return self._writer.handle

    # --- observation building ---------------------------------------------------------

    def _note_namespace(self, ns: Sequence[str]) -> None:
        if not ns:
            return
        namespace = NS_SEP.join(str(item) for item in ns)
        if namespace not in self._pending:
            self._pending[namespace] = []
            self._checkpoint_order[namespace] = []
            self._namespaces.append(namespace)

    def _observation(
        self,
        raw_kind: str,
        *,
        item_id: str,
        body: Any,
        ns: Sequence[str] = (),
        step: int | None = None,
        checkpoint_id: str | None = None,
        tool_call_ref: str | None = None,
        key_kind: str | None = None,
        subordinate_ref: str | None = None,
    ) -> FrameObservation:
        self._note_namespace(ns)
        classification = classify(LANE, raw_kind, body, counter=self._counter)
        if not classification.known:
            self.unknown += 1
        namespace = NS_SEP.join(ns)
        provider_key = deep_agents_key(
            thread_id=self._thread,
            checkpoint_ns=namespace,
            checkpoint_id=checkpoint_id if checkpoint_id is not None else self._last_root,
            step=step,
            item_id=item_id,
            kind=key_kind or classification.kind.value,
        )
        self._pending.setdefault(namespace, []).append(provider_key)
        return FrameObservation(
            provider_key=provider_key,
            raw_kind=raw_kind,
            kind=classification.kind,
            body=body,
            native_turn_ref=self._turn,
            subordinate_ref=subordinate_ref or self._subordinate(ns),
            tool_call_ref=tool_call_ref,
        )

    def _subordinate(self, ns: Sequence[str]) -> str | None:
        if not ns or not str(ns[0]).startswith("tools:"):
            return None
        root = str(ns[0])
        named = self._agent_names.get(root)
        if named:
            return named
        call_id = self._namespace_task.get(root)
        return self._task_names.get(call_id or "") or root

    async def _write(self, observations: Iterable[FrameObservation]) -> None:
        items = list(observations)
        if items:
            await self._writer.write(items)

    async def promote_object(
        self, *, kind: FrameKind, payload: bytes, media_type: str, promotion_key: str
    ) -> str | None:
        """Store an object a frame of `kind` refers to (a human or system message, a whole
        request batch) through the writer and return its `frame-body://` reference, or None
        when the writer stores nothing (no promoter composed, or the profile refuses)."""

        return await self._writer.promote_object(
            kind=kind, payload=payload, media_type=media_type, promotion_key=promotion_key
        )

    # --- lifecycle ------------------------------------------------------------------------

    async def begin(self, *, body: Mapping[str, Any]) -> None:
        await self._write(
            [
                self._observation(
                    "graph.session_init", item_id="session", body={"thread_id": self._thread}
                ),
                self._observation(
                    "graph.invocation_started",
                    item_id=self._turn,
                    body={"thread_id": self._thread, "invocation_id": self._turn, **body},
                ),
            ]
        )

    async def environment(self, manifest: Mapping[str, Any]) -> str:
        """Record the materialization manifest as the attempt's one `environment_materialized`
        frame (keyed `materialization:<invocation>`) and return its digest, which the adapter
        copies into the input point's `channel_facts.materialization_digest`."""

        await self._write(
            [
                self._observation(
                    MANIFEST_RAW_KIND,
                    item_id=f"materialization:{self._turn}",
                    body=dict(manifest),
                )
            ]
        )
        return str(manifest["digest"])

    def capture_model_request(
        self,
        batch: Sequence[BaseMessage],
        *,
        ns: Sequence[str],
        step: int | None,
        node: str | None,
        checkpoint_ns: str,
        invocation_params: Mapping[str, Any],
        metadata: Mapping[str, Any],
        call_index: int,
        follow_up: bool,
    ) -> None:
        """Queue one chat-model call's input (synchronous: the callback runs inline before
        the model is called); `observe`, `flush`, `finish` and `fail` drain the queue."""

        self._model_requests.append(
            model_request_capture(
                batch,
                ns=ns,
                step=step,
                node=node,
                checkpoint_ns=checkpoint_ns,
                invocation_params=invocation_params,
                metadata=metadata,
                call_index=call_index,
                follow_up=follow_up,
                full_requests=self.full_requests,
                secret_values=self._secrets,
            )
        )

    async def _drain_model_requests(self) -> None:
        if not self._model_requests:
            return
        captures, self._model_requests = self._model_requests, []
        observations: list[FrameObservation] = []
        for capture in captures:
            body = dict(capture.body)
            # Tracing Stage 3 (R3-F14): the model was already called (and paid); a payload
            # store that fails one object costs that object's ref, never the turn. The frame
            # is recorded without the ref and names the gap (`promotion_failed`); a later
            # request carrying the same object tries again.
            failed: set[str] = set()
            for digest, payload in capture.objects.items():
                if digest in self._object_refs:
                    continue
                try:
                    self._object_refs[digest] = await self.promote_object(
                        kind=FrameKind.MODEL_REQUEST,
                        payload=payload,
                        media_type=_JSON,
                        promotion_key=f"msg:{digest}",
                    )
                except Exception:
                    logger.warning("a model request object was not promoted", exc_info=True)
                    failed.add(digest)
            system = body.get("system")
            if isinstance(system, Mapping):
                body["system"] = _with_ref(system, self._object_refs, failed)
            body["messages"] = [
                _with_ref(entry, self._object_refs, failed) if isinstance(entry, Mapping) else entry
                for entry in body.get("messages", ())
            ]
            if capture.batch is not None:
                batch_digest, payload = capture.batch
                try:
                    reference = await self.promote_object(
                        kind=FrameKind.MODEL_REQUEST,
                        payload=payload,
                        media_type=_JSON,
                        promotion_key=f"batch:{batch_digest}",
                    )
                except Exception:
                    logger.warning("a model request batch was not promoted", exc_info=True)
                    reference = None
                    body["batch_promotion_failed"] = True
                if reference is not None:
                    body["batch_ref"] = reference
            observations.append(
                self._observation(
                    MODEL_REQUEST_RAW_KIND,
                    item_id=f"call:{capture.call_index}",
                    body=body,
                    ns=capture.ns,
                    step=capture.step,
                )
            )
        await self._write(observations)

    async def observe(self, part: Mapping[str, Any]) -> None:
        await self._drain_model_requests()
        kind = part.get("type")
        ns = tuple(str(item) for item in part.get("ns", ()) or ())
        data = part.get("data")
        if kind == "messages":
            await self._write(self._messages(ns, data))
        elif kind == "updates":
            observations = list(self._flush_all())
            observations.extend(self._updates(ns, data))
            await self._write(observations)
        elif kind == "custom":
            await self._write(self._custom(ns, data))
        elif kind == "checkpoints":
            await self._write(self._flush_all())
            self.observe_checkpoint(part)

    async def flush(self) -> None:
        await self._drain_model_requests()
        await self._write(self._flush_all())

    async def finish(
        self,
        *,
        messages: Sequence[BaseMessage],
        own_messages: Sequence[BaseMessage],
        output_text: str,
        structured_keys: Sequence[str],
        checkpoint_id: str | None,
    ) -> None:
        await self._drain_model_requests()
        observations = list(self._flush_all())
        observations.extend(self.backfill(messages, checkpoint_id=checkpoint_id))
        usage: dict[str, int] = {}
        for message in own_messages:
            if isinstance(message, AIMessage):
                for key, value in usage_counts(message.usage_metadata).items():
                    usage[key] = usage.get(key, 0) + value
        final = next((item for item in reversed(messages) if isinstance(item, AIMessage)), None)
        metadata = final.response_metadata if final is not None else {}
        # Tracing Stage 3 (R3-F9): a turn Mission Control stopped records the stop's marker
        # (`mc_budget_stop`, `mc_fence_stop`, `mc_hook_stop`), not a model's `end_turn`.
        marker = turn_stop_marker(final) if final is not None else None
        stop_reason = marker or str(
            metadata.get("stop_reason") or metadata.get("finish_reason") or "end_turn"
        )
        # The finish frames follow the result point: keyed by it (replay-stable for a
        # terminal reconstruction, which observes no checkpoints part).
        observations.append(
            self._observation(
                "graph.invocation_ended",
                item_id=self._turn,
                checkpoint_id=checkpoint_id,
                body={
                    "invocation_id": self._turn,
                    "outcome": "succeeded",
                    "stop_reason": stop_reason,
                    "message_count": len(messages),
                    "final_message_id": final.id if final is not None else None,
                    # P1 turn 4: the turn's result point, read by the frame identity writer
                    # into `session_turn.point_ref` and `agent_session.checkpoint_ref`.
                    "result_checkpoint_id": checkpoint_id,
                    "thread_id": self._thread,
                    **usage,
                },
            )
        )
        observations.append(
            self._observation(
                "graph.run_result",
                item_id=self._turn,
                checkpoint_id=checkpoint_id,
                body={
                    "status": "finished",
                    "invocation_id": self._turn,
                    "output_digest": _digest(output_text),
                    "output_bytes": len(output_text.encode("utf-8")),
                    "structured_output_keys": sorted(structured_keys),
                    "result_checkpoint_id": checkpoint_id,
                },
            )
        )
        await self._write(observations)

    async def fail(self, error: BaseException, *, unknown_state: bool) -> None:
        """Best effort: a failure to record the failure never masks the original error."""

        body = {
            "invocation_id": self._turn,
            "error_type": type(error).__name__,
            "unknown_state": unknown_state,
            "reason": getattr(error, "reason", None),
        }
        try:
            await self._drain_model_requests()
        except Exception:  # pragma: no cover - logged, the failure frames still follow
            logger.exception("queued model requests of a failed invocation were not recorded")
        observations = [
            *self._flush_all(),
            self._observation("graph.error", item_id=self._turn, body=body),
        ]
        if not unknown_state:
            observations.append(
                self._observation(
                    "graph.run_result",
                    item_id=self._turn,
                    body={
                        "status": "error",
                        "invocation_id": self._turn,
                        "error_type": body["error_type"],
                    },
                )
            )
        try:
            await self._write(observations)
        except Exception:  # pragma: no cover - logged, original error re-raised by caller
            logger.exception("provider frames for a failed invocation were not recorded")

    def backfill(
        self, messages: Sequence[BaseMessage], *, checkpoint_id: str | None = None
    ) -> list[FrameObservation]:
        """Tool results present in the final checkpoint whose closing frame never arrived."""

        observations: list[FrameObservation] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            call_id = str(message.tool_call_id)
            if call_id in self._closed_tool_calls:
                continue
            self._closed_tool_calls.add(call_id)
            observations.append(
                self._observation(
                    "checkpoint_backfill",
                    item_id=call_id,
                    body=frame_message_body(message),
                    checkpoint_id=checkpoint_id,
                    tool_call_ref=call_id,
                )
            )
            if call_id in self._task_names and call_id not in self._ended_tasks:
                observations.append(self._subagent_ended(call_id, message, ()))
        return observations

    # --- stream modes -------------------------------------------------------------------

    def _messages(self, ns: tuple[str, ...], data: Any) -> list[FrameObservation]:
        if not isinstance(data, tuple | list) or len(data) != 2:
            return []
        message, metadata = data
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if ns:
            self._note_namespace(ns)
            if metadata.get("lc_agent_name"):
                self._agent_names.setdefault(ns[0], str(metadata["lc_agent_name"]))
        if not isinstance(message, AIMessageChunk) or not message.id:
            return []  # whole messages are recorded from `updates`, once
        observations: list[FrameObservation] = []
        step = metadata.get("langgraph_step")
        for stream, text in (("text", _text(message.content)), ("thinking", _thinking(message))):
            if not text:
                continue
            key = (str(message.id), stream, NS_SEP.join(ns))
            buffer = self._deltas.setdefault(key, [ns, step, ""])
            buffer[2] += text
            if len(buffer[2].encode("utf-8")) >= self._flush_bytes:
                observations.append(self._flush(key))
        return observations

    def _flush(self, key: tuple[str, str, str]) -> FrameObservation:
        ns, step, text = self._deltas.pop(key)
        index = self._delta_counts.get(key, 0)
        self._delta_counts[key] = index + 1
        message_id, stream, _namespace = key
        raw = "messages.ai_chunk" if stream == "text" else "messages.reasoning_chunk"
        return self._observation(
            raw,
            item_id=f"{message_id}#{index}",
            body={"message_id": message_id, "chunk_index": index, "text": text},
            ns=ns,
            step=step if isinstance(step, int) else None,
        )

    def _flush_all(self) -> list[FrameObservation]:
        return [self._flush(key) for key in list(self._deltas)]

    def _updates(self, ns: tuple[str, ...], data: Any) -> list[FrameObservation]:
        observations: list[FrameObservation] = []
        if not isinstance(data, Mapping):
            return observations
        for node, value in data.items():
            if node == "__metadata__":
                continue
            if node == "__interrupt__":
                interrupts = [
                    {
                        "id": getattr(item, "id", None),
                        "value": jsonable(getattr(item, "value", item)),
                    }
                    for item in (value if isinstance(value, Sequence) else (value,))
                ]
                observations.append(
                    self._observation(
                        "updates.interrupt",
                        item_id=",".join(str(item["id"]) for item in interrupts)
                        or _digest(interrupts),
                        body={"interrupts": interrupts},
                        ns=ns,
                    )
                )
                # The closing evidence the reducer reads: the session now requires action.
                observations.append(
                    self._observation(
                        "updates.interrupt.session_state",
                        item_id=",".join(str(item["id"]) for item in interrupts)
                        or _digest(interrupts),
                        body={
                            "state": "requires_action",
                            "request_ref": ",".join(str(item["id"]) for item in interrupts),
                        },
                        ns=ns,
                    )
                )
                continue
            if not isinstance(value, Mapping):
                continue
            if value.get("_summarization_event") is not None:
                raw_event = value.get("_summarization_event")
                event = jsonable(raw_event)
                digest = _digest(event)
                body: dict[str, Any] = {"node": node, "summary_digest": digest, "event": event}
                if isinstance(raw_event, Mapping) and raw_event.get("summary_message") is not None:
                    # The same summary digest and cutoff the compaction middleware (B4) emits,
                    # so the reducer derives one compaction fact from either frame.
                    summary = raw_event["summary_message"]
                    text = _text(getattr(summary, "content", summary))
                    body["summary_digest"] = (
                        "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
                    )
                    body["cutoff_index"] = raw_event.get("cutoff_index")
                    body["file_path"] = raw_event.get("file_path")
                observations.append(
                    self._observation(
                        "updates.summarization_event",
                        item_id=f"{node}:{digest}",
                        body=body,
                        ns=ns,
                    )
                )
            messages = value.get("messages")
            if isinstance(messages, list | tuple):
                for message in messages:
                    observations.extend(self._message(ns, message))
        return observations

    def _message(self, ns: tuple[str, ...], message: Any) -> list[FrameObservation]:
        observations: list[FrameObservation] = []
        if isinstance(message, AIMessage) and message.id:
            body = message_body(message)
            observations.append(
                self._observation("updates.ai_message", item_id=str(message.id), body=body, ns=ns)
            )
            for call in message.tool_calls:
                call_id = str(call.get("id") or "")
                if not call_id or call_id in self._started_tool_calls:
                    continue
                self._started_tool_calls.add(call_id)
                started = self._observation(
                    "updates.ai_tool_call",
                    item_id=call_id,
                    body={
                        "tool_call_id": call_id,
                        "name": call.get("name"),
                        "args": jsonable(call.get("args")),
                        "args_digest": _digest(call.get("args")),
                        "message_id": message.id,
                    },
                    ns=ns,
                    tool_call_ref=call_id,
                )
                observations.append(started)
                if call.get("name") == TASK_TOOL:
                    observations.append(
                        self._subagent_started(call_id, call, message, ns, started.provider_key)
                    )
            if message.usage_metadata:
                counts = usage_counts(message.usage_metadata)
                if ns:
                    totals = self._usage_by_namespace.setdefault(str(ns[0]), {})
                    for key, value in counts.items():
                        totals[key] = totals.get(key, 0) + value
                observations.append(
                    self._observation(
                        "model.usage",
                        item_id=str(message.id),
                        body={
                            "message_id": message.id,
                            "model": (message.response_metadata or {}).get("model_name"),
                            **counts,
                        },
                        ns=ns,
                    )
                )
        elif isinstance(message, ToolMessage):
            call_id = str(message.tool_call_id)
            self._closed_tool_calls.add(call_id)
            observations.append(
                self._observation(
                    "updates.tool_message",
                    item_id=call_id,
                    body=frame_message_body(message),
                    ns=ns,
                    tool_call_ref=call_id,
                )
            )
            if call_id in self._task_names and call_id not in self._ended_tasks:
                observations.append(self._subagent_ended(call_id, message, ns))
        return observations

    def _subagent_started(
        self,
        call_id: str,
        call: Mapping[str, Any],
        message: AIMessage,
        ns: tuple[str, ...],
        started_key: str,
    ) -> FrameObservation:
        raw_args = call.get("args")
        args: Mapping[str, Any] = raw_args if isinstance(raw_args, Mapping) else {}
        name = str(args.get("subagent_type") or "") or call_id
        self._task_names[call_id] = name
        self._task_started_keys[call_id] = started_key
        description = args.get("description")
        return self._observation(
            "subagent.started",
            item_id=call_id,
            body={
                "name": name,
                "description": str(description) if description is not None else None,
                "tool_call_id": call_id,
                "message_id": message.id,
            },
            ns=ns,
            tool_call_ref=call_id,
            subordinate_ref=name,
        )

    def _subagent_ended(
        self, call_id: str, message: ToolMessage, ns: tuple[str, ...]
    ) -> FrameObservation:
        name = self._task_names.get(call_id) or call_id
        self._ended_tasks.add(call_id)
        namespace = self._task_namespace.get(call_id)
        usage = dict(self._usage_by_namespace.get(namespace, {})) if namespace else {}
        return self._observation(
            "subagent.ended",
            item_id=call_id,
            body={
                "tool_call_id": call_id,
                "name": name,
                "status": message.status,
                "result_digest": _digest(message.content),
                "usage": usage,
                "checkpoint_ns": namespace,
            },
            ns=ns,
            tool_call_ref=call_id,
            subordinate_ref=name,
        )

    def _custom(self, ns: tuple[str, ...], data: Any) -> list[FrameObservation]:
        event_type = data.get("type") if isinstance(data, Mapping) else None
        raw = (
            f"custom.{event_type}"
            if isinstance(event_type, str) and event_type.startswith("mc.")
            else "custom"
        )
        item = data.get("id") if isinstance(data, Mapping) else None
        tool_call_ref = data.get("tool_call_id") if isinstance(data, Mapping) else None
        return [
            self._observation(
                raw,
                item_id=str(item) if item else _digest(data),
                body=jsonable(data),
                ns=ns,
                tool_call_ref=str(tool_call_ref) if tool_call_ref else None,
                key_kind=raw,
            )
        ]


def _with_ref(
    entry: Mapping[str, Any], refs: Mapping[str, str | None], failed: set[str] | None = None
) -> dict[str, Any]:
    item = dict(entry)
    digest = str(item.get("digest"))
    reference = refs.get(digest)
    if reference is not None:
        item["ref"] = reference
    elif failed is not None and digest in failed:
        item["promotion_failed"] = True
    return item


__all__ = [
    "DELTA_FLUSH_BYTES",
    "MANIFEST_RAW_KIND",
    "MODEL_REQUEST_RAW_KIND",
    "NS_SEP",
    "SOURCE_SANDBOX_UPLOAD",
    "SOURCE_STATE_CHANNEL",
    "TASK_TOOL",
    "DeepAgentFrameRecorder",
    "ManifestFile",
    "ModelRequestCapture",
    "frame_message_body",
    "materialization_manifest",
    "message_body",
    "model_request_capture",
]
