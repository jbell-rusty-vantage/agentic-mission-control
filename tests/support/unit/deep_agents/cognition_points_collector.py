"""Builders, constants and fakes that other test files import.

Moved from tests/unit/deep_agents/test_cognition_points_collector.py.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from mission_control.adapters.deep_agents.checkpoint_reads import checkpoint_parent_id
from mission_control.domain.execution.checkpoint_lineage import (
    ROOT_CHECKPOINT_NS,
    CheckpointInvocationPlan,
    submission_invocation_id,
)

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
