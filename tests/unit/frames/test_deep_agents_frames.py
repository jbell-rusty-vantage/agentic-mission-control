"""Deep Agents frame writer: a real `create_deep_agent` run streams frames before derivation.

Offline: deterministic fake chat models, `InMemorySaver`, the in-memory checkpoint lineage
and the in-memory FrameStore with the Postgres semantics (C1 acceptance shape).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid5

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Interrupt

from mission_control.adapters.deep_agents import DeepAgentRuntimeAdapter, ExactDeepAgentMaterializer
from mission_control.adapters.deep_agents.frames import (
    DeepAgentFrameRecorder,
    ManifestFile,
    frame_message_body,
    materialization_manifest,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.frames.kinds import UnknownKindCounter
from mission_control.application.frames.sink import InMemoryFrameStore
from mission_control.application.frames.streams import frame_envelope
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    MaterializedWorkspace,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    RuntimeInvocation,
)
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.subscriptions.streams import StreamScope
from tests.acceptance.control_plane.test_wp_cp_040 import (
    SkillReadingModel,
    exact_fixture,
    registry,
)
from tests.fixtures.checkpoint_lineage import activity_attempt, bind_unit, stage_unit
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.provider_frames import (
    INSTALLATION,
    SCOPE,
    in_memory_store,
    opened_writer,
)
from tests.fixtures.workspace_closures import InMemoryWorkspaceClosures
from tests.unit.operations.test_operation_execution import operation_request


def _unit_binding():  # type: ignore[no-untyped-def]
    binding, _profile, bundle = exact_fixture()
    unit = stage_unit(request_scope=SCOPE, run_id=binding.run_id, operation_id=binding.operation_id)
    return bind_unit(binding, unit), bundle, unit


async def _planned(binding: Any, lineage: CheckpointLineageService) -> RuntimeInvocation:
    payload = operation_request().model_dump(mode="python")
    payload.update(
        request_scope=SCOPE,
        identity=OperationAttemptIdentity(
            run_id=binding.run_id,
            operation_id=binding.operation_id,
            operation_attempt=binding.operation_attempt,
        ),
        execution_runtime="deep_agent",
        native_placement=None,
        **lane_fields(binding),
        runtime_unit=binding.runtime_unit,
    )
    request = OperationExecutionRequest.model_validate(payload)
    bound = bind_operation_execution_request(request)
    plan = await lineage.observe_attempt(bound, activity_attempt(1), dispatching=True)
    return RuntimeInvocation(
        binding=bound,
        prompt_segments=request.prompt_segments,
        workspace=MaterializedWorkspace(
            workspace_id=request.workspace.workspace_id,
            namespace_id=request.workspace.namespace_id,
            provider=request.workspace.provider,
            runtime_digest=request.workspace.runtime_digest,
            image_digest=request.workspace.image_digest,
            mount_manifest_digest=sha256_digest("mounts"),
        ),
        checkpoint_plan=plan,
    )


def _store_for(unit: Any) -> InMemoryFrameStore:
    store = InMemoryFrameStore()
    run_id = uuid5(INSTALLATION, unit.belllabs_run_id)
    store.register_run(SCOPE, unit.belllabs_run_id, run_id, {unit.unit_key: uuid5(run_id, "a")})
    return store


@pytest.mark.asyncio
async def test_actual_deep_agent_run_leaves_an_ordered_deduplicated_frame_sequence() -> None:
    binding, bundle, unit = _unit_binding()
    store = _store_for(unit)
    model = SkillReadingModel()
    closures = InMemoryWorkspaceClosures()
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, model)),
        frames=store,
        closures=closures,
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    invocation = await _planned(binding, lineage)
    result = await adapter.execute(
        invocation, {"environment:FIXTURE_TOKEN": "fixture-secret-value"}
    )
    assert result.output_text == "SKILL-MD-IN-MESSAGES-040 observed and followed."

    run_id = uuid5(INSTALLATION, unit.belllabs_run_id)
    frames = await store.frames_for_run(SCOPE, run_id)
    kinds = [frame.kind for frame in frames]
    # 1.4.4: the environment frame right after `begin`, one `model_request` before each
    # model response (two calls: the Skill read, then the answer).
    assert kinds[:3] == [
        FrameKind.SESSION_INIT,
        FrameKind.TURN_STARTED,
        FrameKind.ENVIRONMENT_MATERIALIZED,
    ]
    assert kinds[-2:] == [FrameKind.TURN_ENDED, FrameKind.RUN_RESULT]
    assert kinds.index(FrameKind.TOOL_CALL_STARTED) < kinds.index(FrameKind.TOOL_CALL_COMPLETED)
    assert FrameKind.MESSAGE in kinds
    assert kinds.count(FrameKind.MODEL_REQUEST) == kinds.count(FrameKind.MESSAGE) == 2
    for request in (frame for frame in frames if frame.kind == FrameKind.MODEL_REQUEST):
        response = next(
            frame
            for frame in frames
            if frame.kind == FrameKind.MESSAGE and frame.arrival_ordinal > request.arrival_ordinal
        )
        assert request.raw_kind == "model.request"
        assert all(
            frame.kind != FrameKind.MODEL_REQUEST
            for frame in frames
            if request.arrival_ordinal < frame.arrival_ordinal < response.arrival_ordinal
        )
    assert [frame.arrival_ordinal for frame in frames] == list(range(1, len(frames) + 1))
    tool = next(frame for frame in frames if frame.kind == FrameKind.TOOL_CALL_COMPLETED)
    assert tool.tool_call_ref == "skill-read-040" and tool.raw_kind == "updates.tool_message"
    assert all(frame.native_session_ref == binding.cognitive_session_namespace for frame in frames)
    assert all(
        frame.native_turn_ref == invocation.checkpoint_plan.invocation_id for frame in frames
    )  # type: ignore[union-attr]
    run_result = frames[-1]
    assert '"status":"finished"' in run_result.body_excerpt
    assert "fixture-secret-value" not in "".join(frame.body_excerpt for frame in frames)
    handle_id = frames[0].harness_execution_id
    assert store.turns(handle_id)[0]["ended_frame_id"] == frames[-2].frame_id
    assert store._executions[handle_id].start.native_identity["frame_capture_profile"] == "none"  # type: ignore[union-attr]
    # P4.2: every key after the first checkpoint names the root point it followed, and the
    # finish frames name the result point; the stream envelope exposes it.
    assert result.checkpoint is not None
    result_id = result.checkpoint.result_key.checkpoint_id
    scope = StreamScope(installation_id="i", application_id="biotech", tenant_id="t")
    envelopes = [frame_envelope(frame, scope=scope).payload for frame in frames]
    assert all(payload["lane_profile"] == "deep_agents" for payload in envelopes)
    assert envelopes[0]["after_point_ref"] is None  # before any checkpoint
    assert envelopes[-1]["after_point_ref"] == {
        "kind": "checkpoint",
        "thread_id": binding.cognitive_session_namespace,
        "checkpoint_ns": "",
        "checkpoint_id": result_id,
    }
    after_refs = [
        payload["after_point_ref"]["checkpoint_id"]
        for payload in envelopes
        if payload["after_point_ref"] is not None
    ]
    assert len(set(after_refs)) > 1 and after_refs == sorted(after_refs)  # uuid6: time ordered
    assert tool.provider_key.startswith(f"{binding.cognitive_session_namespace}::")
    # The input point carries the manifest digest; the result point the workspace ref.
    environment = frames[2]
    assert environment.raw_kind == "materialization.manifest"
    assert environment.provider_key == (
        f"{binding.cognitive_session_namespace}::::materialization:"
        f"{invocation.checkpoint_plan.invocation_id}:environment_materialized"  # type: ignore[union-attr]
    )
    manifest = json.loads(environment.body_excerpt)
    assert set(manifest) == {"files", "skills", "mcp_servers", "model", "digest"}
    points = result.cognition_points
    assert points[0].channel_facts["materialization_digest"] == manifest["digest"]
    assert all("materialization_digest" not in point.channel_facts for point in points[1:])
    # OVE-204 slice 5: the result point names the attempt's Workspace Closure.
    closure = closures.only()
    assert points[-1].workspace_checkpoint_ref == closure.ref
    assert closure.ref.startswith(f"workspace-closure://{closure.closure_id}#sha256:")
    assert closure.boundary == "attempt_settled" and closure.backend == "state"
    assert closure.harness_execution_id == str(handle_id)
    assert closure.result_checkpoint.checkpoint_id == result_id
    assert closure.files and closure.complete
    assert all(b"fixture-secret-value" not in body for body in closures.bodies.values())

    # The same unit re-executed is reconstructed from its terminal checkpoint: the writer
    # re-observes the same turn and every stream-independent key dedupes (begin, the
    # environment, the finish frames keyed by the result point). The one row the
    # reconstruction adds is the tool result it backfills from the final state, keyed by
    # the result point it was observed after (the live frame named the point it followed);
    # the reducer settles a tool call once by its ref, so the row is evidence only.
    again = await adapter.execute(invocation, {})
    assert again.checkpoint is not None and again.checkpoint.classification == "terminal_unobserved"
    replayed = await store.frames_for_run(SCOPE, run_id)
    assert len(replayed) == len(frames) + 1
    (backfilled,) = [frame for frame in replayed if frame.raw_kind == "checkpoint_backfill"]
    assert backfilled.tool_call_ref == "skill-read-040"
    assert (
        backfilled.provider_key
        == f"{binding.cognitive_session_namespace}::{result_id}::skill-read-040:tool_call_completed"
    )
    assert model.calls == 2


class _Writer:
    def __init__(self) -> None:
        self.observations: list[Any] = []
        self.promoted: list[tuple[str, str]] = []

    async def write(self, observations: Any) -> Any:
        self.observations.extend(observations)

    async def promote_object(
        self, *, kind: FrameKind, payload: bytes, media_type: str, promotion_key: str
    ) -> str | None:
        del payload, media_type
        self.promoted.append((kind.value, promotion_key))
        return None


def _recorder(counter: UnknownKindCounter | None = None) -> tuple[DeepAgentFrameRecorder, _Writer]:
    writer = _Writer()
    recorder = DeepAgentFrameRecorder(
        writer,  # type: ignore[arg-type]
        thread_id="thread-1",
        invocation_id="turn-1",
        counter=counter or UnknownKindCounter(),
        delta_flush_bytes=8,
    )
    return recorder, writer


@pytest.mark.asyncio
async def test_stream_parts_map_to_frames_with_subordinate_attribution() -> None:
    recorder, writer = _recorder()
    subagent_ns = ("tools:task-123", "model:abc")
    await recorder.observe(
        {
            "type": "messages",
            "ns": subagent_ns,
            "data": (
                AIMessageChunk(content="Searching the literature", id="sub-msg"),
                {"langgraph_step": 2, "lc_agent_name": "researcher"},
            ),
        }
    )
    await recorder.observe(
        {
            "type": "updates",
            "ns": subagent_ns,
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            content="",
                            id="sub-msg",
                            tool_calls=[
                                {"name": "pubmed_search", "args": {"q": "rapamycin"}, "id": "c-9"}
                            ],
                            usage_metadata={
                                "input_tokens": 10,
                                "output_tokens": 2,
                                "total_tokens": 12,
                            },
                        )
                    ]
                }
            },
        }
    )
    await recorder.observe(
        {
            "type": "updates",
            "ns": (),
            "data": {
                "tools": {
                    "messages": [
                        ToolMessage(content="boom", tool_call_id="c-8", status="error"),
                    ]
                },
                "SummarizationMiddleware.before_model": {"_summarization_event": {"cut": 4}},
                "__interrupt__": (Interrupt(value={"action": "approve"}, id="int-1"),),
            },
        }
    )
    await recorder.observe(
        {"type": "custom", "ns": (), "data": {"type": "mc.hook_result", "id": "h1"}}
    )
    await recorder.observe({"type": "custom", "ns": (), "data": {"progress": 3}})
    kinds = [item.kind for item in writer.observations]
    assert kinds == [
        FrameKind.MESSAGE_DELTA,
        FrameKind.MESSAGE,
        FrameKind.TOOL_CALL_STARTED,
        FrameKind.USAGE,
        FrameKind.TOOL_CALL_FAILED,
        FrameKind.AFTER_COMPACTION,
        FrameKind.APPROVAL_REQUESTED,
        FrameKind.SESSION_STATE,
        FrameKind.HOOK_RESULT,
        FrameKind.UNKNOWN,
    ]
    sub = writer.observations[:4]
    assert {item.subordinate_ref for item in sub} == {"researcher"}
    assert all(item.subordinate_ref is None for item in writer.observations[4:])
    assert writer.observations[2].tool_call_ref == "c-9"
    assert writer.observations[4].tool_call_ref == "c-8"
    assert recorder.unknown == 1
    keys = [item.provider_key for item in writer.observations]
    assert len(set(keys)) == len(keys)
    assert keys[0].startswith("thread-1:tools:task-123|model:abc::2:sub-msg#0")


@pytest.mark.asyncio
async def test_backfill_closes_tool_results_the_stream_never_delivered() -> None:
    recorder, writer = _recorder()
    await recorder.observe(
        {
            "type": "updates",
            "ns": (),
            "data": {"tools": {"messages": [ToolMessage(content="ok", tool_call_id="seen")]}},
        }
    )
    messages = [
        ToolMessage(content="ok", tool_call_id="seen"),
        ToolMessage(content="late", tool_call_id="missed"),
    ]
    await recorder.finish(
        messages=messages,
        own_messages=[],
        output_text="done",
        structured_keys=(),
        checkpoint_id="cp-1",
    )
    backfill = [item for item in writer.observations if item.raw_kind == "checkpoint_backfill"]
    assert [item.tool_call_ref for item in backfill] == ["missed"]
    assert backfill[0].kind == FrameKind.TOOL_CALL_COMPLETED
    assert [item.kind for item in writer.observations][-2:] == [
        FrameKind.TURN_ENDED,
        FrameKind.RUN_RESULT,
    ]


@pytest.mark.asyncio
async def test_failure_records_error_then_run_result_unless_state_is_unknown() -> None:
    recorder, writer = _recorder()
    await recorder.fail(RuntimeError("model exploded"), unknown_state=False)
    assert [item.kind for item in writer.observations] == [FrameKind.ERROR, FrameKind.RUN_RESULT]
    assert "model exploded" not in str([item.body for item in writer.observations])
    recorder, writer = _recorder()
    await recorder.fail(RuntimeError("lineage"), unknown_state=True)
    assert [item.kind for item in writer.observations] == [FrameKind.ERROR]
    assert writer.observations[0].body["unknown_state"] is True


@pytest.mark.asyncio
async def test_recorder_through_the_real_writer_dedupes_replayed_parts() -> None:
    store, run_id = in_memory_store()
    writer, _handle = await opened_writer(store)
    recorder = DeepAgentFrameRecorder(writer, thread_id="thread-1", invocation_id="turn-1")
    part = {
        "type": "updates",
        "ns": (),
        "data": {"model": {"messages": [AIMessage(content="hi", id="m-1")]}},
    }
    await recorder.observe(part)
    await recorder.observe(part)
    frames = await store.frames_for_run(SCOPE, run_id)
    assert [frame.kind for frame in frames] == [FrameKind.MESSAGE]
    assert recorder.receipt.duplicate == 1


def _checkpoint_part(checkpoint_id: str, step: int, ns: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "checkpoints",
        "ns": ns,
        "data": {
            "config": {
                "configurable": {
                    "thread_id": "thread-1",
                    "checkpoint_ns": "|".join(ns),
                    "checkpoint_id": checkpoint_id,
                }
            },
            "metadata": {"step": step},
        },
    }


@pytest.mark.asyncio
async def test_keys_name_the_root_point_each_frame_followed() -> None:
    """P4.2 `after_point_ref`: the checkpoint slot of every key is the last root checkpoint the
    recorder had seen; nested frames name the root point too; the window of a checkpoint holds
    the keys recorded since the previous one of its namespace."""

    recorder, writer = _recorder()
    await recorder.observe(
        {"type": "updates", "ns": (), "data": {"model": {"messages": [AIMessage("a", id="m-1")]}}}
    )
    await recorder.observe(_checkpoint_part("cp-1", 1))
    await recorder.observe(
        {"type": "updates", "ns": (), "data": {"model": {"messages": [AIMessage("b", id="m-2")]}}}
    )
    await recorder.observe(
        {
            "type": "updates",
            "ns": ("tools:t-1",),
            "data": {"model": {"messages": [AIMessage("c", id="m-3")]}},
        }
    )
    await recorder.observe(_checkpoint_part("child-1", 0, ("tools:t-1",)))
    await recorder.observe(_checkpoint_part("cp-2", 2))
    keys = [item.provider_key for item in writer.observations]
    assert keys == [
        "thread-1::::m-1:message",
        "thread-1::cp-1::m-2:message",
        "thread-1:tools:t-1:cp-1::m-3:message",
    ]
    assert recorder.observed_checkpoints() == {"cp-1": 1, "cp-2": 2}
    assert recorder.observed_checkpoints(ns="tools:t-1") == {"child-1": 0}
    assert recorder.frame_keys_for("cp-1") == (keys[0],)
    assert recorder.frame_keys_for("cp-2") == (keys[1],)
    assert recorder.frame_keys_for("child-1", ns="tools:t-1") == (keys[2],)
    assert recorder.nested_namespaces() == ("tools:t-1",)
    assert recorder.pending_frame_keys() == ()


@pytest.mark.asyncio
async def test_task_tool_calls_bracket_a_subagent_with_its_usage_and_namespace() -> None:
    """P3.6: the `task` call yields `subagent_started`, its tool message `subagent_ended`
    (closing) with the usage summed from the child's message frames under its namespace; the
    child's namespace is mapped to the call and its name."""

    recorder, writer = _recorder()
    await recorder.observe(
        {
            "type": "updates",
            "ns": (),
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            "",
                            id="m-1",
                            tool_calls=[
                                {
                                    "name": "task",
                                    "args": {
                                        "description": "Review it.",
                                        "subagent_type": "reviewer",
                                    },
                                    "id": "task-1",
                                }
                            ],
                        )
                    ]
                }
            },
        }
    )
    await recorder.observe(_checkpoint_part("cp-1", 1))
    child = ("tools:t-9",)
    # The adapter's tool callback binds the call to its LangGraph task namespace (R3-F5).
    recorder.bind_task_namespace("task-1", "tools:t-9")
    await recorder.observe(
        {
            "type": "updates",
            "ns": child,
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            "looks good",
                            id="c-1",
                            usage_metadata={
                                "input_tokens": 5,
                                "output_tokens": 2,
                                "total_tokens": 7,
                            },
                        )
                    ]
                }
            },
        }
    )
    await recorder.observe(_checkpoint_part("child-1", 1, child))
    await recorder.observe(
        {
            "type": "updates",
            "ns": (),
            "data": {"tools": {"messages": [ToolMessage("looks good", tool_call_id="task-1")]}},
        }
    )
    kinds = [item.kind for item in writer.observations]
    assert kinds == [
        FrameKind.MESSAGE,
        FrameKind.TOOL_CALL_STARTED,
        FrameKind.SUBAGENT_STARTED,
        FrameKind.MESSAGE,
        FrameKind.USAGE,
        FrameKind.TOOL_CALL_COMPLETED,
        FrameKind.SUBAGENT_ENDED,
    ]
    started, ended = writer.observations[2], writer.observations[6]
    assert started.raw_kind == "subagent.started" and ended.raw_kind == "subagent.ended"
    assert started.body == {
        "name": "reviewer",
        "description": "Review it.",
        "tool_call_id": "task-1",
        "message_id": "m-1",
    }
    assert started.provider_key == "thread-1::::task-1:subagent_started"
    assert started.tool_call_ref == ended.tool_call_ref == "task-1"
    assert started.subordinate_ref == ended.subordinate_ref == "reviewer"
    assert ended.body["name"] == "reviewer" and ended.body["status"] == "success"
    assert ended.body["usage"] == {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
    assert ended.body["checkpoint_ns"] == "tools:t-9"
    assert ended.body["result_digest"].startswith("sha256:")
    # The child's frames name the child by the `task` call that spawned its namespace.
    assert writer.observations[3].subordinate_ref == "reviewer"
    assert recorder.task_call_for("tools:t-9") == "task-1"
    assert recorder.task_started_key("task-1") == writer.observations[1].provider_key
    assert recorder.agent_name("tools:t-9") == "reviewer"
    assert recorder.frame_keys_for("cp-1") == tuple(
        item.provider_key for item in writer.observations[:3]
    )
    assert recorder.frame_keys_for("child-1", ns="tools:t-9") == tuple(
        item.provider_key for item in writer.observations[3:5]
    )


def test_materialization_manifest_digest_is_stable_and_names_destinations() -> None:
    facts = {
        "skills": [{"name": "s", "mount_root": "/skills/s", "bundle_digest": "sha256:" + "a" * 64}],
        "mcp_servers": ["pubmed"],
        "model": {"logical_id": "model.x", "revision": 1, "digest": "sha256:" + "b" * 64},
        "state_files": [{"path": "/skills/s/SKILL.md", "bytes": 3, "digest": "sha256:" + "c" * 64}],
    }
    files = [ManifestFile("/inputs/a.md", "ctx-a", b"hello", "sandbox_upload")]
    first = materialization_manifest(facts, files)
    again = materialization_manifest(dict(facts), list(files))
    assert first == again and first["digest"].startswith("sha256:")
    assert [item["path"] for item in first["files"]] == ["/inputs/a.md", "/skills/s/SKILL.md"]
    assert first["files"][0] == {
        "path": "/inputs/a.md",
        "slot": "ctx-a",
        "bytes": 5,
        "digest": "sha256:" + hashlib.sha256(b"hello").hexdigest(),
        "destination": "sandbox_upload",
    }
    assert first["files"][1]["destination"] == "state_channel"
    without = {key: value for key, value in first.items() if key != "digest"}
    assert materialization_manifest(facts, files)["digest"] == first["digest"]
    assert "digest" not in without
    changed = materialization_manifest({**facts, "mcp_servers": []}, files)
    assert changed["digest"] != first["digest"]


# --- Tracing Stage 3 ----------------------------------------------------------------------


def _task_call(call_id: str, description: str) -> dict[str, Any]:
    return {
        "name": "task",
        "args": {"description": description, "subagent_type": "reviewer"},
        "id": call_id,
    }


def _child_update(ns: tuple[str, ...], message_id: str, total: int) -> dict[str, Any]:
    usage = {"input_tokens": total - 1, "output_tokens": 1, "total_tokens": total}
    return {
        "type": "updates",
        "ns": ns,
        "data": {
            "model": {
                "messages": [AIMessage("ok", id=message_id, usage_metadata=usage)]  # type: ignore[arg-type]
            }
        },
    }


@pytest.mark.asyncio
async def test_parallel_task_calls_bind_to_their_own_namespaces() -> None:
    """R3-F5: two `task` calls of one step run concurrently; the second call's child may
    reach the stream first. Each namespace is bound by the tool callback's exact
    `(tool_call_id, checkpoint_ns)` pair, never by order of appearance."""

    recorder, writer = _recorder()
    await recorder.observe(
        {
            "type": "updates",
            "ns": (),
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            "",
                            id="m-1",
                            tool_calls=[
                                _task_call("task-a", "Review A."),
                                _task_call("task-b", "Review B."),
                            ],
                        )
                    ]
                }
            },
        }
    )
    recorder.bind_task_namespace("task-a", "tools:ns-a")
    recorder.bind_task_namespace("task-b", "tools:ns-b")
    recorder.bind_task_namespace("task-z", "tools:ns-a|tools:inner")  # a nested spawn: ignored
    await recorder.observe(_child_update(("tools:ns-b",), "c-b", 11))  # the second child first
    await recorder.observe(_child_update(("tools:ns-a",), "c-a", 7))
    await recorder.observe(
        {
            "type": "updates",
            "ns": (),
            "data": {
                "tools": {
                    "messages": [
                        ToolMessage("A done", tool_call_id="task-a"),
                        ToolMessage("B done", tool_call_id="task-b"),
                    ]
                }
            },
        }
    )
    ended = {
        item.tool_call_ref: item.body
        for item in writer.observations
        if item.kind == FrameKind.SUBAGENT_ENDED
    }
    assert ended["task-a"]["checkpoint_ns"] == "tools:ns-a"
    assert ended["task-a"]["usage"]["total_tokens"] == 7
    assert ended["task-b"]["checkpoint_ns"] == "tools:ns-b"
    assert ended["task-b"]["usage"]["total_tokens"] == 11
    assert recorder.task_call_for("tools:ns-a") == "task-a"
    assert recorder.task_call_for("tools:ns-b|model:x") == "task-b"


@pytest.mark.asyncio
async def test_a_real_parallel_task_step_binds_each_child_by_its_tool_run() -> None:
    """R3-F5 over deepagents itself: the tool run's `langgraph_checkpoint_ns` is the child's
    stream namespace, one per `task` call of the parallel step."""

    from deepagents import create_deep_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from mission_control.adapters.deep_agents.adapter import _TaskNamespaceObserver

    totals = {"Review A.": 7, "Review B.": 11}

    class Scripted(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "scripted-parallel-tasks"

        def bind_tools(self, tools: Any, **kwargs: Any) -> Scripted:
            del tools, kwargs
            return self

        def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
            del args, kwargs
            first = next(item for item in messages if isinstance(item, HumanMessage))
            text = str(first.content)
            if text in totals:  # a child: answer with its own usage
                usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": totals[text]}
                message = AIMessage("ok", id=f"child-{text}", usage_metadata=usage)  # type: ignore[arg-type]
            elif any(isinstance(item, ToolMessage) for item in messages):
                message = AIMessage("done", id="parent-2")
            else:
                message = AIMessage(
                    "",
                    id="parent-1",
                    tool_calls=[
                        _task_call("task-a", "Review A."),
                        _task_call("task-b", "Review B."),
                    ],
                )
            return ChatResult(generations=[ChatGeneration(message=message)])

    model = Scripted()
    agent = create_deep_agent(
        model=model,
        subagents=[
            {
                "name": "reviewer",
                "description": "Reviews.",
                "system_prompt": "Review.",
                "model": model,
            }
        ],
    )
    recorder, writer = _recorder()
    async for part in agent.astream(
        {"messages": [HumanMessage(content="go")]},
        {"callbacks": [_TaskNamespaceObserver(recorder)]},
        stream_mode=["updates", "messages", "custom", "checkpoints"],
        subgraphs=True,
        version="v2",
    ):
        await recorder.observe(part)
    await recorder.flush()
    ended = {
        item.tool_call_ref: item.body
        for item in writer.observations
        if item.kind == FrameKind.SUBAGENT_ENDED
    }
    assert ended["task-a"]["usage"]["total_tokens"] == 7
    assert ended["task-b"]["usage"]["total_tokens"] == 11
    assert ended["task-a"]["checkpoint_ns"] != ended["task-b"]["checkpoint_ns"]
    for call_id in ("task-a", "task-b"):
        assert recorder.task_call_for(ended[call_id]["checkpoint_ns"]) == call_id


@pytest.mark.asyncio
async def test_a_mission_control_stop_is_told_apart_from_a_model_answer() -> None:
    """R3-F9: the stop's marker survives in the message body and names the turn's stop
    reason; it is no usage frame."""

    recorder, writer = _recorder()
    stop = AIMessage(
        "Mission Control ended this turn: the operation budget is exhausted (tokens.total).",
        id="stop-1",
        additional_kwargs={"mc_budget_stop": {"tokens.total": {"limit": 1, "spent": 2}}},
    )
    await recorder.observe({"type": "updates", "ns": (), "data": {"model": {"messages": [stop]}}})
    await recorder.finish(
        messages=[stop], own_messages=[stop], output_text="", structured_keys=(), checkpoint_id="cp"
    )
    message = next(item for item in writer.observations if item.kind == FrameKind.MESSAGE)
    assert message.body["mc_stop"] == {
        "marker": "mc_budget_stop",
        "detail": {"tokens.total": {"limit": 1, "spent": 2}},
    }
    assert FrameKind.USAGE not in [item.kind for item in writer.observations]
    ended = next(item for item in writer.observations if item.kind == FrameKind.TURN_ENDED)
    assert ended.body["stop_reason"] == "mc_budget_stop"
    assert "mc_stop" not in frame_message_body(AIMessage("answer", id="a-1"))


class _FailingWriter(_Writer):
    async def promote_object(
        self, *, kind: FrameKind, payload: bytes, media_type: str, promotion_key: str
    ) -> str | None:
        del kind, payload, media_type
        if promotion_key.startswith("msg:"):
            raise OSError("payload store down")
        return "frame-body://batch"


@pytest.mark.asyncio
async def test_a_failing_payload_store_costs_the_ref_not_the_turn() -> None:
    """R3-F14: the model was already called; a promotion error records the request frame
    without the ref and with `promotion_failed`, and the turn goes on."""

    from langchain_core.messages import HumanMessage

    writer = _FailingWriter()
    recorder = DeepAgentFrameRecorder(writer, thread_id="thread-1", invocation_id="turn-1")  # type: ignore[arg-type]
    recorder.capture_model_request(
        [HumanMessage(content="hello", id="h-1")],
        ns=(),
        step=1,
        node="model",
        checkpoint_ns="model:t",
        invocation_params={},
        metadata={},
        call_index=1,
        follow_up=False,
    )
    await recorder.flush()
    (request,) = [item for item in writer.observations if item.kind == FrameKind.MODEL_REQUEST]
    (entry,) = request.body["messages"]
    assert entry["promotion_failed"] is True and "ref" not in entry
