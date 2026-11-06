"""WP-TR-4 (TRACING-PROPOSAL §P5.3): the seed head with the injected message on the Deep
Agents lane, over the in-memory saver.

After a copied lineage, `DeepAgentsTimeTravel._inject_message` records the message as a
`messages` write of the copied point and puts one more root checkpoint after it (the
`messages` version advanced, the point's stamps copied, `source: fork`), so the delta
history of the new head folds to the copied conversation plus the message as its last
human message; a second call for the same fork request reuses the head.

Tracing Stage 3 (R2-1): over a delta `messages` channel (Deep Agents' shape) at a point that is
not the thread's last, the seed head is the state at the point plus the message (the copy
leaves the point's own pending writes, the source's next step, out of the derived thread),
with and without a `_DeltaSnapshot` blob at the point; without a message the copy is as
before.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

import pytest
from deepagents._messages_reducer import _messages_delta_reducer
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.channels.delta import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from mission_control.adapters.deep_agents.checkpoint_reads import (
    ROOT_CHECKPOINT_NS,
    checkpoint_parent_id,
    root_checkpoint_config,
)
from mission_control.adapters.deep_agents.cognition_points import fold_delta_history
from mission_control.adapters.deep_agents.time_travel import (
    FORK_SEED_STAMP,
    DeepAgentsTimeTravel,
)
from mission_control.application.execution.harness.time_travel import ForkSeedRequest
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointRecord,
    UnitLocationFacts,
    point_id_for,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from tests.unit.deep_agents.test_cognition_points_collector import (
    THREAD,
    _graph,
    _lineage,
    _plan,
)

MESSAGE = "Prefer companies with CLIA labs."


async def _messages_at(saver: InMemorySaver, checkpoint_id: str) -> list[object]:
    config = root_checkpoint_config(THREAD, checkpoint_id)
    item = await saver.aget_tuple(config)
    assert item is not None
    stored = item.checkpoint.get("channel_values") or {}
    if "messages" in stored:
        return list(stored["messages"])
    history = await saver.aget_delta_channel_history(config=config, channels=["messages"])
    return list(fold_delta_history(history["messages"]))


@pytest.mark.asyncio
async def test_the_seed_head_carries_the_message_after_the_point() -> None:
    saver = InMemorySaver()
    agent = _graph(saver)
    plan = _plan("activity-attempt:11111111-1111-5111-8111-111111111111")
    config = {
        "configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS},
        "metadata": plan.invocation_metadata(),
    }
    await agent.ainvoke({"messages": [HumanMessage(content="one", id="h-1")]}, config=config)
    lineage = await _lineage(saver)
    point_id = lineage[-1][0]
    before = await _messages_at(saver, point_id)
    assert [getattr(message, "type", None) for message in before][:2] == ["human", "ai"]

    head_id = await DeepAgentsTimeTravel._inject_message(
        saver, thread_id=THREAD, point_id=point_id, message=MESSAGE, fork_request_id="fork-1"
    )

    assert head_id != point_id
    head = await saver.aget_tuple(root_checkpoint_config(THREAD, head_id))
    assert head is not None
    assert checkpoint_parent_id(head) == point_id
    metadata = dict(head.metadata or {})
    assert metadata[FORK_SEED_STAMP] == "fork-1"
    assert metadata["source"] == "fork"
    point = await saver.aget_tuple(root_checkpoint_config(THREAD, point_id))
    assert point is not None
    # The point's stamps travel with the head (the derived attempt's classifier reads them).
    for name, value in (point.metadata or {}).items():
        if name.startswith("belllabs_"):
            assert metadata[name] == value
    assert metadata["step"] == (point.metadata or {}).get("step", -1) + 1
    assert (
        head.checkpoint["channel_versions"]["messages"]
        != (point.checkpoint["channel_versions"]["messages"])
    )
    after = await _messages_at(saver, head_id)
    assert len(after) == len(before) + 1
    last = after[-1]
    assert getattr(last, "type", None) == "human"
    assert getattr(last, "content", None) == MESSAGE
    assert getattr(last, "id", None) == "fork-seed:fork-1"
    # The point itself reads as before: the message is a pending write applied at the head.
    assert await _messages_at(saver, point_id) == before
    # The head is the thread's latest checkpoint.
    latest = await saver.aget_tuple(
        {"configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS}}
    )
    assert latest is not None and latest.checkpoint["id"] == head_id


@pytest.mark.asyncio
async def test_injecting_twice_for_one_fork_reuses_the_head() -> None:
    saver = InMemorySaver()
    agent = _graph(saver)
    plan = _plan("activity-attempt:11111111-1111-5111-8111-111111111111")
    config = {
        "configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS},
        "metadata": plan.invocation_metadata(),
    }
    await agent.ainvoke({"messages": [HumanMessage(content="one", id="h-1")]}, config=config)
    point_id = (await _lineage(saver))[-1][0]
    first = await DeepAgentsTimeTravel._inject_message(
        saver, thread_id=THREAD, point_id=point_id, message=MESSAGE, fork_request_id="fork-1"
    )
    again = await DeepAgentsTimeTravel._inject_message(
        saver, thread_id=THREAD, point_id=point_id, message=MESSAGE, fork_request_id="fork-1"
    )
    assert again == first
    other = await DeepAgentsTimeTravel._inject_message(
        saver, thread_id=THREAD, point_id=point_id, message=MESSAGE, fork_request_id="fork-2"
    )
    assert other != first
    assert len(await _messages_at(saver, other)) == len(await _messages_at(saver, first))


# --- Tracing Stage 3 (R2-1): a delta `messages` channel and an intermediate point ----------

DELTA_THREAD = "belllabs/stage/source/gen/1"
DERIVED_THREAD = "belllabs/stage/derived/gen/1"
STAMPS = {
    "belllabs_binding_digest": "sha256:" + "1" * 64,
    "belllabs_state_schema_digest": "sha256:" + "2" * 64,
}


class DeltaState(TypedDict):
    """Deep Agents' `messages` channel shape: a delta channel snapshotting every 50 updates."""

    messages: Annotated[
        list[AnyMessage], DeltaChannel(_messages_delta_reducer, snapshot_frequency=50)
    ]


class SnapshottingState(TypedDict):
    """The same channel storing a `_DeltaSnapshot` blob at every update."""

    messages: Annotated[
        list[AnyMessage], DeltaChannel(_messages_delta_reducer, snapshot_frequency=1)
    ]


def _delta_graph(saver: InMemorySaver, *, snapshot_frequency: int = 50) -> Any:
    """`START -> a -> b` over a delta `messages` channel."""

    def step_a(state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage(content="step-a", id="ai-a")]}

    def step_b(state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage(content="step-b", id="ai-b")]}

    graph = StateGraph(DeltaState if snapshot_frequency == 50 else SnapshottingState)
    graph.add_node("a", step_a)
    graph.add_node("b", step_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    return graph.compile(checkpointer=saver)


async def _thread_messages(saver: InMemorySaver, thread: str, checkpoint_id: str) -> list[str]:
    config = root_checkpoint_config(thread, checkpoint_id)
    item = await saver.aget_tuple(config)
    assert item is not None
    stored = (item.checkpoint.get("channel_values") or {}).get("messages")
    if stored is not None:
        values = getattr(stored, "value", stored)
    else:
        history = await saver.aget_delta_channel_history(config=config, channels=["messages"])
        values = fold_delta_history(history["messages"])
    return [str(message.content) for message in values]


async def _source_lineage(saver: InMemorySaver) -> list[str]:
    ids: list[str] = []
    async for item in saver.alist(
        {"configurable": {"thread_id": DELTA_THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS}}
    ):
        ids.append(str(item.config["configurable"]["checkpoint_id"]))
    ids.reverse()
    return ids


def _seed_request(point_id: str, parent_id: str | None, *, message: str | None) -> ForkSeedRequest:
    key = QualifiedCheckpointKey(
        checkpointer_ref_digest=DELTA_DIGEST,
        thread_id=DELTA_THREAD,
        checkpoint_ns=ROOT_CHECKPOINT_NS,
        checkpoint_id=point_id,
        parent_checkpoint_id=parent_id,
    )
    unit_key = "bl-unit-v1:" + "ab" * 32
    location = UnitLocationFacts(family="stage_graph", node_key="S2", iteration=0, cycle=0)
    source = CognitionPointRecord(
        point_id=point_id_for("run-source", unit_key, 1, "checkpoint", point_id),
        coordinate=CognitionCoordinate(
            run_id="run-source",
            unit_key=unit_key,
            execution_generation=1,
            point=CheckpointPoint(key=key),
        ),
        lane_profile="deep_agents",
        location=location,
        roles=("intermediate",),
        seedable=True,
        written_by="adapter",
        recorded_at=datetime.now(UTC),
    )
    return ForkSeedRequest(
        source=source,
        derived_run_id="run-derived",
        derived_unit_key="bl-unit-v1:" + "ba" * 32,
        derived_namespace=DERIVED_THREAD,
        derived_invocation_id="sha256:" + "3" * 64,
        fork_request_id="fork-delta",
        message=message,
    )


DELTA_DIGEST = "sha256:" + "4" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_frequency", [50, 1])
async def test_a_seed_head_at_an_intermediate_point_is_the_point_plus_the_message(
    snapshot_frequency: int,
) -> None:
    """The point between `a` and `b` holds `b`'s output as its pending writes (the next step's);
    the head is the state at the point plus the message, never `b`'s output. With
    `snapshot_frequency=1` every update stores a `_DeltaSnapshot` blob at the checkpoint."""

    saver = InMemorySaver()
    agent = _delta_graph(saver, snapshot_frequency=snapshot_frequency)
    await agent.ainvoke(
        {"messages": [HumanMessage(content="hi", id="h1")]},
        {"configurable": {"thread_id": DELTA_THREAD}, "metadata": STAMPS},
    )
    lineage = await _source_lineage(saver)
    point_id, parent_id = lineage[-2], lineage[-3]
    at_point = await _thread_messages(saver, DELTA_THREAD, point_id)
    assert at_point == ["hi", "step-a"]

    lane = DeepAgentsTimeTravel({DELTA_DIGEST: saver})
    receipt = await lane.seed_fork(_seed_request(point_id, parent_id, message=MESSAGE))
    head = receipt.derived.point
    assert isinstance(head, CheckpointPoint)
    assert head.key.parent_checkpoint_id == point_id
    assert await _thread_messages(saver, DERIVED_THREAD, head.key.checkpoint_id) == [
        *at_point,
        MESSAGE,
    ]
    assert receipt.native_artifacts["seed_head_message_count"] == "3"
    # The copied point itself reads as the source point, and the source is untouched.
    assert await _thread_messages(saver, DERIVED_THREAD, point_id) == at_point
    assert await _thread_messages(saver, DELTA_THREAD, lineage[-1]) == ["hi", "step-a", "step-b"]
    # `state-as-of` the point reads the same conversation (the snapshot blob unwrapped).
    state = await lane.read_as_of(_seed_request(point_id, parent_id, message=None).source)
    assert [message.text for message in state.state.messages] == at_point


@pytest.mark.asyncio
async def test_a_seed_without_a_message_copies_the_point_with_its_pending_writes() -> None:
    """The no-message path is unchanged: the derived thread holds the point as the source
    does, its pending writes included."""

    saver = InMemorySaver()
    agent = _delta_graph(saver)
    await agent.ainvoke(
        {"messages": [HumanMessage(content="hi", id="h1")]},
        {"configurable": {"thread_id": DELTA_THREAD}, "metadata": STAMPS},
    )
    lineage = await _source_lineage(saver)
    point_id, parent_id = lineage[-2], lineage[-3]
    lane = DeepAgentsTimeTravel({DELTA_DIGEST: saver})
    receipt = await lane.seed_fork(_seed_request(point_id, parent_id, message=None))
    head = receipt.derived.point
    assert isinstance(head, CheckpointPoint) and head.key.checkpoint_id == point_id
    assert "seed_head_message_count" not in receipt.native_artifacts
    source = await saver.aget_tuple(root_checkpoint_config(DELTA_THREAD, point_id))
    derived = await saver.aget_tuple(root_checkpoint_config(DERIVED_THREAD, point_id))
    assert source is not None and derived is not None
    assert [write[1:3] for write in derived.pending_writes or ()] == [
        write[1:3] for write in source.pending_writes or ()
    ]
    assert await _thread_messages(saver, DERIVED_THREAD, point_id) == ["hi", "step-a"]
