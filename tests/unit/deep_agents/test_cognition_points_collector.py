"""The Deep Agents point collector over a real LangGraph saver (P1 turn 4, WP-1).

A two-node graph with an `add_messages` channel runs two invocations on one thread with
the lineage stamps the adapter uses; the collector walks the second invocation's lineage
from its result back to the first's result and folds one observation per root checkpoint.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

import mission_control.adapters.deep_agents.cognition_points as cognition_points_module
from mission_control.adapters.deep_agents.adapter import _TaskNamespaceObserver
from mission_control.adapters.deep_agents.checkpoint_reads import (
    checkpoint_parent_id,
    root_checkpoint_config,
)
from mission_control.adapters.deep_agents.cognition_points import collect_points
from mission_control.adapters.deep_agents.frames import DeepAgentFrameRecorder
from mission_control.adapters.deep_agents.time_travel import DeepAgentsTimeTravel
from mission_control.domain.execution.checkpoint_lineage import (
    ROOT_CHECKPOINT_NS,
    CheckpointCapture,
    CheckpointInvocationPlan,
    submission_invocation_id,
)
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointRecord,
    UnitLocationFacts,
    point_id_for,
)
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from tests.fixtures.provider_frames import SCOPE as FRAME_SCOPE
from tests.fixtures.provider_frames import in_memory_store, opened_writer

SCOPE = "mc/0192a4f0-0000-7000-8000-00000000b10e/biotech/9287e246-224b-5814-bc00-44bb5396e0c5"
UNIT_KEY = "bl-unit-v1:" + "cd" * 32
DIGEST = "sha256:" + "ef" * 32
THREAD = "belllabs/goal/run/epoch/1/session/1/role/executor"


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    files: dict[str, Any]


def _graph(saver: InMemorySaver) -> Any:
    calls = {"n": 0}

    def think(state: State) -> dict[str, Any]:
        calls["n"] += 1
        return {
            "messages": [
                AIMessage(
                    content=f"answer {calls['n']}",
                    id=f"ai-{calls['n']}",
                    usage_metadata={"input_tokens": 8, "output_tokens": 12, "total_tokens": 20},
                )
            ]
        }

    def write(state: State) -> dict[str, Any]:
        return {"files": {**state.get("files", {}), f"/work/{calls['n']}.md": {"content": "x"}}}

    graph = StateGraph(State)
    graph.add_node("think", think)
    graph.add_node("write", write)
    graph.add_edge(START, "think")
    graph.add_edge("think", "write")
    graph.add_edge("write", END)
    return graph.compile(checkpointer=saver)


def _plan(attempt_ref: str) -> CheckpointInvocationPlan:
    return CheckpointInvocationPlan(
        request_scope=SCOPE,
        unit_key=UNIT_KEY,
        execution_generation=1,
        claim_fence=1,
        namespace=THREAD,
        invocation_id=submission_invocation_id(UNIT_KEY, 1),
        checkpointer_ref_digest=DIGEST,
        binding_digest=DIGEST,
        state_schema_digest=DIGEST,
        attempt_ref=attempt_ref,
    )


async def _lineage(saver: InMemorySaver) -> list[tuple[str, str | None, int | None]]:
    items = []
    async for item in saver.alist(
        {"configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS}}
    ):
        items.append(
            (
                str(item.config["configurable"]["checkpoint_id"]),
                checkpoint_parent_id(item),
                (item.metadata or {}).get("step"),
            )
        )
    items.reverse()
    return items


@pytest.mark.asyncio
async def test_collect_points_folds_each_root_checkpoint_of_the_attempt_lineage() -> None:
    saver = InMemorySaver()
    agent = _graph(saver)
    plan = _plan("activity-attempt:11111111-1111-5111-8111-111111111111")
    config = {
        "configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS},
        "metadata": plan.invocation_metadata(),
    }
    await agent.ainvoke({"messages": [HumanMessage(content="one", id="h-1")]}, config=config)
    first_run = await _lineage(saver)
    source_id = first_run[-1][0]
    # Iteration 2 continues the thread from iteration 1's result, as the adapter pins it.
    second_plan = plan.model_copy(
        update={
            "expected_source": QualifiedCheckpointKey(
                checkpointer_ref_digest=DIGEST,
                thread_id=THREAD,
                checkpoint_id=source_id,
                parent_checkpoint_id=first_run[-1][1],
            )
        }
    )
    await agent.ainvoke(
        {"messages": [HumanMessage(content="two", id="h-2")]},
        config={**config, "configurable": {**config["configurable"], "checkpoint_id": source_id}},
    )
    lineage = await _lineage(saver)
    second_run = [item for item in lineage if item[0] not in {x[0] for x in first_run}]
    result_id, result_parent, _step = second_run[-1]
    capture = CheckpointCapture(
        namespace=THREAD,
        invocation_id=second_plan.invocation_id,
        source_key=second_plan.expected_source,
        result_key=QualifiedCheckpointKey(
            checkpointer_ref_digest=DIGEST,
            thread_id=THREAD,
            checkpoint_id=result_id,
            parent_checkpoint_id=result_parent,
        ),
        ancestry_verified=True,
        stamped_checkpoint_count=len(second_run),
        redacted_summary_digest=DIGEST,
    )

    points = await collect_points(saver, second_plan, capture, recorder=None)

    assert [point.locator for point in points] == [item[0] for item in second_run]
    first, *_middle, last = points
    assert first.source == "input" and "input" in first.roles
    assert first.parent_locator is None
    assert first.parent_point is not None and first.parent_point.locator == source_id
    assert last.roles == ("leaf", "result")
    assert all(point.parent_locator == points[i - 1].locator for i, point in enumerate(points) if i)
    assert all(point.attempt_ref == plan.attempt_ref for point in points)
    assert all(point.native_turn_ref == plan.invocation_id for point in points)
    # LangGraph's `input` checkpoint holds the state before the input is applied (the input
    # is its pending write), so iteration 2's first point still sees iteration 1's two
    # messages; its result sees h-1, ai-1, h-2 and ai-2, folded by identity.
    assert first.message_count == 2
    assert last.message_count == 4
    # Usage advances only on the step whose model call produced it.
    assert sum(point.usage_delta.get("tokens.total_tokens", 0) for point in points) == 20
    assert last.files_digest is not None and first.files_digest is not None
    assert last.files_digest != first.files_digest
    assert last.channel_facts["message_count"] == 4
    assert all(point.seedable for point in points)
    # The walk is pinned to the plan's checkpointer and namespace.
    assert all(point.point.key.checkpointer_ref_digest == DIGEST for point in points)
    assert all(point.point.key.thread_id == THREAD for point in points)
    assert await saver.aget_tuple(root_checkpoint_config(THREAD, result_id)) is not None

    # 1.4.4 (TR-D6): the reconciler's recorder-less walk through the lane port yields the
    # same points (keys, parents, roles, facts) without the attempt and turn identities the
    # settlement adds, and refuses a checkpointer the worker did not register.
    from mission_control.adapters.deep_agents.time_travel import DeepAgentsTimeTravel
    from mission_control.application.execution.harness.time_travel import TimeTravelUnsupported

    lane = DeepAgentsTimeTravel({DIGEST: saver})
    rederived = await lane.collect_points(
        namespace=THREAD,
        checkpointer_ref_digest=DIGEST,
        source_locator=source_id,
        result_locator=result_id,
    )
    assert [
        point.model_dump(mode="json", exclude={"attempt_ref", "native_turn_ref"})
        for point in rederived
    ] == [
        point.model_dump(mode="json", exclude={"attempt_ref", "native_turn_ref"})
        for point in points
    ]
    assert all(point.attempt_ref is None and point.native_turn_ref is None for point in rederived)
    with pytest.raises(TimeTravelUnsupported, match="checkpointer_not_registered"):
        await lane.collect_points(
            namespace=THREAD,
            checkpointer_ref_digest="sha256:" + "0" * 64,
            source_locator=source_id,
            result_locator=result_id,
        )


# --- 1.4.4 (P3.6): a sync subagent's nested checkpoints become points ----------------------


def _parent_with_child(saver: InMemorySaver) -> Any:
    """A parent whose `model` node calls `task` once and whose `tools` node runs the child
    graph inside the tool (the way deepagents' `task` tool invokes a sync subagent, inheriting
    the parent's checkpointer under the `tools:<task_id>` namespace)."""

    def child_model(state: State) -> dict[str, Any]:
        return {
            "messages": [
                AIMessage(
                    content="reviewed: fine",
                    id="child-ai-1",
                    usage_metadata={"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
                )
            ]
        }

    child_graph = StateGraph(State)
    child_graph.add_node("child_model", child_model)
    child_graph.add_edge(START, "child_model")
    child_graph.add_edge("child_model", END)
    child = child_graph.compile()

    def model(state: State) -> dict[str, Any]:
        if any(isinstance(item, ToolMessage) for item in state["messages"]):
            return {
                "messages": [
                    AIMessage(
                        content="done",
                        id="ai-2",
                        usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                    )
                ]
            }
        return {
            "messages": [
                AIMessage(
                    content="",
                    id="ai-1",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {"description": "Review it.", "subagent_type": "reviewer"},
                            "id": "task-1",
                        }
                    ],
                    usage_metadata={"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
                )
            ]
        }

    @tool("task")
    def task(description: str, subagent_type: str) -> str:
        """Run a sync subagent."""

        del subagent_type
        result = child.invoke({"messages": [HumanMessage(content=description, id="child-h-1")]})
        return str(result["messages"][-1].content)

    def tools(state: State, config: RunnableConfig) -> dict[str, Any]:
        # The tool runs as a tool run (`on_tool_start` carries its call id and namespace),
        # the way the tools node runs deepagents' `task` tool.
        call = state["messages"][-1].tool_calls[0]
        return {"messages": [task.invoke({**call, "type": "tool_call"}, config)]}

    def route(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    graph = StateGraph(State)
    graph.add_node("model", model)
    graph.add_node("tools", tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=saver)


class _ManifestReader:
    def __init__(self, manifest: Mapping[str, Any] | None) -> None:
        self.manifest_body = manifest
        self.asked: list[tuple[str, int]] = []

    async def manifest(
        self, harness_execution_id: str, generation: int
    ) -> Mapping[str, Any] | None:
        self.asked.append((harness_execution_id, generation))
        return self.manifest_body


def _record(point: Any, *, harness_execution_id: str) -> CognitionPointRecord:
    coordinate = CognitionCoordinate(
        run_id="run-1",
        unit_key=UNIT_KEY,
        execution_generation=1,
        harness_execution_id=harness_execution_id,
        point=point.point,
    )
    return CognitionPointRecord(
        point_id=point_id_for("run-1", UNIT_KEY, 1, coordinate.kind, coordinate.locator),
        coordinate=coordinate,
        lane_profile="deep_agents",
        location=UnitLocationFacts(family="stage_graph", node_key="s1", iteration=0, cycle=0),
        parent_locator=point.parent_locator,
        ordinal=point.ordinal,
        source=point.source,
        roles=point.roles,
        channel_facts=point.channel_facts,
        written_by="adapter",
        recorded_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_a_sync_subagent_namespace_becomes_points_under_its_parent_step() -> None:
    saver = InMemorySaver()
    agent = _parent_with_child(saver)
    plan = _plan("activity-attempt:22222222-2222-5222-8222-222222222222")
    store, _run_id = in_memory_store(request_scope=FRAME_SCOPE)
    writer, handle = await opened_writer(store)
    recorder = DeepAgentFrameRecorder(writer, thread_id=THREAD, invocation_id=plan.invocation_id)
    config = {
        "configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS},
        "metadata": plan.invocation_metadata(),
        "callbacks": [_TaskNamespaceObserver(recorder)],
    }
    await recorder.begin(body={"classification": "not_submitted"})
    async for part in agent.astream(
        {"messages": [HumanMessage(content="one", id="h-1")]},
        config,
        stream_mode=["updates", "messages", "custom", "checkpoints"],
        subgraphs=True,
        version="v2",
        durability="sync",
    ):
        await recorder.observe(part)
    await recorder.flush()
    lineage = await _lineage(saver)
    result_id, result_parent, _step = lineage[-1]
    await recorder.finish(
        messages=[],
        own_messages=[],
        output_text="done",
        structured_keys=(),
        checkpoint_id=result_id,
    )
    capture = CheckpointCapture(
        namespace=THREAD,
        invocation_id=plan.invocation_id,
        source_key=None,
        result_key=QualifiedCheckpointKey(
            checkpointer_ref_digest=DIGEST,
            thread_id=THREAD,
            checkpoint_id=result_id,
            parent_checkpoint_id=result_parent,
        ),
        ancestry_verified=True,
        stamped_checkpoint_count=len(lineage),
        redacted_summary_digest=DIGEST,
    )
    frames = await store.frames_for_execution(FRAME_SCOPE, handle.harness_execution_id, 1)
    kinds = [frame.kind for frame in frames]
    assert FrameKind.SUBAGENT_STARTED in kinds and FrameKind.SUBAGENT_ENDED in kinds
    assert kinds.index(FrameKind.TOOL_CALL_STARTED) < kinds.index(FrameKind.SUBAGENT_STARTED)
    assert kinds.index(FrameKind.SUBAGENT_STARTED) < kinds.index(FrameKind.TOOL_CALL_COMPLETED)
    assert kinds.index(FrameKind.TOOL_CALL_COMPLETED) < kinds.index(FrameKind.SUBAGENT_ENDED)
    ended = next(frame for frame in frames if frame.kind == FrameKind.SUBAGENT_ENDED)
    assert ended.closing and ended.subordinate_ref == "reviewer" and ended.tool_call_ref == "task-1"
    assert '"usage":{"input_tokens":4,"output_tokens":6,"total_tokens":10}' in ended.body_excerpt
    (namespace,) = recorder.nested_namespaces()
    assert namespace.startswith("tools:")
    child_message = next(
        frame for frame in frames if frame.kind == FrameKind.MESSAGE and frame.subordinate_ref
    )
    assert child_message.subordinate_ref == "reviewer"
    assert child_message.provider_key.startswith(f"{THREAD}:{namespace}:")

    points = await collect_points(
        saver, plan, capture, recorder=recorder, manifest_digest="sha256:" + "ab" * 32
    )

    roots = [point for point in points if point.point.key.is_root]
    children = [point for point in points if not point.point.key.is_root]
    assert [point.locator for point in roots] == [item[0] for item in lineage]
    assert roots[0].channel_facts["materialization_digest"] == "sha256:" + "ab" * 32
    assert children, "the child's nested checkpoints are points"
    assert all(point.subordinate_ref == "reviewer" for point in children)
    assert all(point.point.key.checkpoint_ns == namespace for point in children)
    assert all(not point.seedable for point in children)
    assert all("result" not in point.roles for point in children)
    first, *_rest, last = children if len(children) > 1 else (children[0], children[0])
    assert "subagent_root" in first.roles
    assert "leaf" in last.roles
    # The child's first point links to the root point of the step that spawned it: the one
    # whose frames hold the `task` call's `tool_call_started`.
    started_key = recorder.task_started_key("task-1")
    assert started_key is not None
    spawning = next(point for point in roots if started_key in point.frame_keys)
    assert first.parent_locator == spawning.locator
    assert all(
        point.parent_locator == children[index - 1].locator
        for index, point in enumerate(children)
        if index
    )
    assert last.message_count == 2  # the task description and the child's answer
    assert sum(point.usage_delta.get("tokens.total_tokens", 0) for point in children) == 10
    assert child_message.provider_key in {key for point in children for key in point.frame_keys}
    assert all(point.native_observed_at is not None for point in children)
    assert all(point.harness_execution_id == str(handle.harness_execution_id) for point in points)
    # The nested checkpoints are not root points: the recorder-less walk stays root-only.
    assert len(await collect_points(saver, plan, capture, recorder=None)) == len(roots)

    # TR-D8: `read_as_of` opens a nested point by its namespace, says where every file lived,
    # and lists the manifest's sandbox uploads when a reader is composed (digests only).
    manifest = {
        "files": [
            {
                "path": "/inputs/a.md",
                "slot": "ctx",
                "bytes": 3,
                "digest": "sha256:" + "cd" * 32,
                "destination": "sandbox_upload",
            },
            {
                "path": "/skills/s/SKILL.md",
                "slot": None,
                "bytes": 2,
                "digest": "sha256:" + "ef" * 32,
                "destination": "state_channel",
            },
        ],
        "skills": [],
        "mcp_servers": [],
        "model": {},
        "digest": "sha256:" + "ab" * 32,
    }
    reader = _ManifestReader(manifest)
    lane = DeepAgentsTimeTravel({DIGEST: saver}, manifests=reader)
    child_state = await lane.read_as_of(
        _record(last, harness_execution_id=str(handle.harness_execution_id))
    )
    assert isinstance(child_state.point.coordinate.point, CheckpointPoint)
    assert [message.role for message in child_state.state.messages] == ["human", "ai"]
    assert child_state.materialization_digest == "sha256:" + "ab" * 32
    uploads = [file for file in child_state.state.files if file.source == "sandbox_upload"]
    assert [(file.path, file.digest, file.size_bytes) for file in uploads] == [
        ("/inputs/a.md", "sha256:" + "cd" * 32, 3)
    ]
    assert reader.asked == [(str(handle.harness_execution_id), 1)]
    root_state = await lane.read_as_of(
        _record(roots[-1], harness_execution_id=str(handle.harness_execution_id))
    )
    assert all(
        file.source == "state_channel"
        for file in root_state.state.files
        if file.path.startswith("/work/")
    )
    assert root_state.materialization_digest == "sha256:" + "ab" * 32  # from the manifest frame
    unread = DeepAgentsTimeTravel({DIGEST: saver})
    plain = await unread.read_as_of(_record(roots[0], harness_execution_id=None))
    assert plain.materialization_digest == "sha256:" + "ab" * 32  # the input point's channel fact
    assert "materialization manifest unread: no manifest reader composed" in plain.state.withheld


# --- Tracing Stage 3: bounded walks degrade, never charge or link from absence ---------------


class _SlowAfter:
    """A saver whose reads become slow after `fast` of them (a budget that runs out)."""

    def __init__(self, inner: InMemorySaver, *, fast: int, delay: float) -> None:
        self._inner = inner
        self._fast = fast
        self._delay = delay
        self.reads = 0

    async def aget_tuple(self, config: Any) -> Any:
        self.reads += 1
        if self.reads > self._fast:
            await asyncio.sleep(self._delay)
        return await self._inner.aget_tuple(config)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def _two_runs(saver: InMemorySaver) -> tuple[CheckpointInvocationPlan, CheckpointCapture]:
    """Two invocations on one thread; the capture of the second (source: the first's result)."""

    agent = _graph(saver)
    plan = _plan("activity-attempt:33333333-3333-5333-8333-333333333333")
    config = {
        "configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS},
        "metadata": plan.invocation_metadata(),
    }
    await agent.ainvoke({"messages": [HumanMessage(content="one", id="h-1")]}, config=config)
    first_run = await _lineage(saver)
    source_id, source_parent, _step = first_run[-1]
    second_plan = plan.model_copy(
        update={
            "expected_source": QualifiedCheckpointKey(
                checkpointer_ref_digest=DIGEST,
                thread_id=THREAD,
                checkpoint_id=source_id,
                parent_checkpoint_id=source_parent,
            )
        }
    )
    await agent.ainvoke(
        {"messages": [HumanMessage(content="two", id="h-2")]},
        config={**config, "configurable": {**config["configurable"], "checkpoint_id": source_id}},
    )
    second_run = [
        item for item in await _lineage(saver) if item[0] not in {x[0] for x in first_run}
    ]
    result_id, result_parent, _step = second_run[-1]
    capture = CheckpointCapture(
        namespace=THREAD,
        invocation_id=second_plan.invocation_id,
        source_key=second_plan.expected_source,
        result_key=QualifiedCheckpointKey(
            checkpointer_ref_digest=DIGEST,
            thread_id=THREAD,
            checkpoint_id=result_id,
            parent_checkpoint_id=result_parent,
        ),
        ancestry_verified=True,
        stamped_checkpoint_count=len(second_run),
        redacted_summary_digest=DIGEST,
    )
    return second_plan, capture


@pytest.mark.asyncio
async def test_a_walk_cut_short_backwards_charges_the_first_point_only_its_own_step() -> None:
    """R2-14 and R1-F7: the budget ran out after the result was read. The one folded point
    measures its usage from its real parent (not from zero, which charged it the thread's
    whole usage) and names that parent although it was not walked."""

    saver = InMemorySaver()
    plan, capture = await _two_runs(saver)
    slow = _SlowAfter(saver, fast=0, delay=0.02)

    points = await collect_points(
        slow,  # type: ignore[arg-type]
        plan,
        capture,
        recorder=None,
        budget_seconds=0.001,
    )

    (result,) = points
    assert result.locator == capture.result_key.checkpoint_id
    assert result.channel_facts["points_status"] == "incomplete"
    assert result.parent_locator == capture.result_key.parent_checkpoint_id
    assert result.parent_point is None
    # The result step (`write`) called no model: its delta is empty, not the thread's 40.
    assert result.usage_delta == {}


@pytest.mark.asyncio
async def test_a_walk_cut_short_while_folding_names_the_result_points_parent() -> None:
    """R1-F7: the result folded alone after the budget ran out keeps its parent's id."""

    saver = InMemorySaver()
    plan, capture = await _two_runs(saver)
    # The backward walk reads the three checkpoints fast; the source's usage read is slow.
    slow = _SlowAfter(saver, fast=3, delay=0.05)

    points = await collect_points(
        slow,  # type: ignore[arg-type]
        plan,
        capture,
        recorder=None,
        budget_seconds=0.03,
    )

    first, result = points
    assert first.parent_point is not None
    assert first.parent_point.locator == capture.source_key.checkpoint_id  # type: ignore[union-attr]
    assert first.parent_locator is None
    assert "result" in result.roles and result.channel_facts["points_status"] == "incomplete"
    assert result.parent_locator == capture.result_key.parent_checkpoint_id
    assert result.parent_locator != first.locator  # the gap is named, not closed


async def _child_run(saver: InMemorySaver) -> tuple[Any, ...]:
    agent = _parent_with_child(saver)
    plan = _plan("activity-attempt:44444444-4444-5444-8444-444444444444")
    store, _run_id = in_memory_store(request_scope=FRAME_SCOPE)
    writer, _handle = await opened_writer(store)
    recorder = DeepAgentFrameRecorder(writer, thread_id=THREAD, invocation_id=plan.invocation_id)
    config = {
        "configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS},
        "metadata": plan.invocation_metadata(),
        "callbacks": [_TaskNamespaceObserver(recorder)],
    }
    async for part in agent.astream(
        {"messages": [HumanMessage(content="one", id="h-1")]},
        config,
        stream_mode=["updates", "messages", "custom", "checkpoints"],
        subgraphs=True,
        version="v2",
        durability="sync",
    ):
        await recorder.observe(part)
    await recorder.flush()
    lineage = await _lineage(saver)
    result_id, result_parent, _step = lineage[-1]
    capture = CheckpointCapture(
        namespace=THREAD,
        invocation_id=plan.invocation_id,
        source_key=None,
        result_key=QualifiedCheckpointKey(
            checkpointer_ref_digest=DIGEST,
            thread_id=THREAD,
            checkpoint_id=result_id,
            parent_checkpoint_id=result_parent,
        ),
        ancestry_verified=True,
        stamped_checkpoint_count=len(lineage),
        redacted_summary_digest=DIGEST,
    )
    return plan, capture, recorder


@pytest.mark.asyncio
async def test_a_long_child_namespace_degrades_to_incomplete_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3-F6: a child namespace longer than the walk bound no longer turns a completed turn
    into a lineage incident; the points found are kept and the gap is named."""

    saver = InMemorySaver()
    plan, capture, recorder = await _child_run(saver)
    (namespace,) = recorder.nested_namespaces()
    assert len(recorder.observed_checkpoints(ns=namespace)) > 1
    monkeypatch.setattr(cognition_points_module, "MAX_SUBAGENT_POINT_WALK", 1)

    points = await collect_points(saver, plan, capture, recorder=recorder)

    roots = [point for point in points if point.point.key.is_root]
    children = [point for point in points if not point.point.key.is_root]
    assert len(children) == 1
    facts = roots[-1].channel_facts
    assert facts["points_status"] == "incomplete" and facts["subagent_points"] == "incomplete"
    assert facts["subagent_namespaces_unwalked"] == [namespace]
    assert facts["points_walked"] == len(roots)


@pytest.mark.asyncio
async def test_child_namespaces_follow_the_walk_budget_and_name_the_gap() -> None:
    """R2-14 / R3-F6: the nested walk shares the settlement's budget; a spent budget names
    the child namespaces it did not walk on the result point (the reconciler re-walks only
    the root lineage), and a sufficient one walks them as before."""

    saver = InMemorySaver()
    plan, capture, recorder = await _child_run(saver)
    (namespace,) = recorder.nested_namespaces()

    complete = await collect_points(saver, plan, capture, recorder=recorder, budget_seconds=60)
    assert any(not point.point.key.is_root for point in complete)
    result = next(point for point in complete if "result" in point.roles)
    assert "subagent_points" not in result.channel_facts

    slow = _SlowAfter(saver, fast=0, delay=0.02)
    spent = await collect_points(
        slow,  # type: ignore[arg-type]
        plan,
        capture,
        recorder=recorder,
        budget_seconds=0.001,
    )
    assert all(point.point.key.is_root for point in spent)
    facts = spent[-1].channel_facts
    assert facts["points_status"] == "incomplete"
    assert facts["subagent_namespaces_unwalked"] == [namespace]
