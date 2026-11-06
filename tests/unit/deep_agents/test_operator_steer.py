"""Steer with context on Deep Agents (owner 2026-11-06): a gentle `cooperative_inject`.

The operator's steer reaches the running turn at its next model call, as a checkpointed human
message, with no cancel, no extra graph node and no lost steer when the turn ends first.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from mission_control.adapters.deep_agents.describe import DEEP_AGENTS_DESCRIBE
from mission_control.adapters.deep_agents.steering import (
    STEER_KWARG,
    STEER_PREAMBLE,
    OperatorSteerMiddleware,
    SteerInbox,
    SteerItem,
)
from mission_control.application.execution.harness.inject import (
    SteerFollowUpLane,
    merged_steer,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import PromptSegment, PromptTrustClass
from mission_control.domain.execution.lane_turns import LANE_COMMAND_SEMANTICS

KEY = "binding-1"


def segment(text: str, ref: str = "context-packet:sha256:1") -> PromptSegment:
    return PromptSegment(
        source_ref=ref,
        source_revision=1,
        trust_class=PromptTrustClass.ADMITTED_INPUT,
        content=text,
        rendered_digest=sha256_digest(text),
    )


class RecordingModel(FakeMessagesListChatModel):
    """Scripted replies; records every call's input messages."""

    seen: list[list[BaseMessage]] = []

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        type(self).seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


def agent_and_inbox(steer_during_tool: str | None) -> tuple[Any, SteerInbox, InMemorySaver]:
    inbox = SteerInbox()
    inbox.open(KEY)

    @tool
    def look() -> str:
        """Look at the workspace."""
        if steer_during_tool is not None:
            inbox.put(KEY, SteerItem(delivery_key="cmd-1", segment=segment(steer_during_tool)))
        return "nothing here"

    RecordingModel.seen = []
    model = RecordingModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "look", "args": {}, "id": "t1"}]),
            AIMessage(content="done"),
        ]
    )
    saver = InMemorySaver()
    agent = create_agent(
        model=model,
        tools=[look],
        middleware=[OperatorSteerMiddleware(inbox, KEY)],
        checkpointer=saver,
    )
    return agent, inbox, saver


@pytest.mark.asyncio
async def test_a_steer_reaches_the_next_model_call_and_the_checkpointed_state() -> None:
    agent, inbox, _saver = agent_and_inbox("Also mention the parameter count.")
    config = {"configurable": {"thread_id": "t"}}
    result = await agent.ainvoke({"messages": [HumanMessage(content="task")]}, config)

    second_call = RecordingModel.seen[1]
    steer = second_call[-1]
    assert isinstance(steer, HumanMessage)
    assert steer.content.startswith(STEER_PREAMBLE)
    assert "Also mention the parameter count." in steer.content
    assert steer.additional_kwargs[STEER_KWARG]["delivery_key"] == "cmd-1"
    # Persisted in the thread, right before the reply it produced (one turn, no restart).
    kinds = [type(m).__name__ for m in result["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "HumanMessage", "AIMessage"]
    assert result["messages"][3].id == steer.id
    state = await agent.aget_state(config)
    assert any(getattr(m, "id", None) == steer.id for m in state.values["messages"])
    assert inbox.close(KEY) == []


@pytest.mark.asyncio
async def test_the_steer_adds_no_checkpoint_beyond_an_unsteered_turn() -> None:
    steered, _, steered_saver = agent_and_inbox("steer")
    plain, _, plain_saver = agent_and_inbox(None)
    for agent in (steered, plain):
        await agent.ainvoke(
            {"messages": [HumanMessage(content="task")]}, {"configurable": {"thread_id": "t"}}
        )
    count = lambda saver: len(list(saver.list({"configurable": {"thread_id": "t"}})))  # noqa: E731
    assert count(steered_saver) == count(plain_saver)


def test_a_steer_for_no_running_turn_is_kept_for_the_follow_up() -> None:
    inbox = SteerInbox()
    assert inbox.put(KEY, SteerItem("cmd-1", segment("late"))) is False
    inbox.open(KEY)
    assert inbox.put(KEY, SteerItem("cmd-2", segment("a"))) is True
    assert inbox.put(KEY, SteerItem("cmd-2", segment("a"))) is True  # idempotent per delivery
    assert [item.delivery_key for item in inbox.close(KEY)] == ["cmd-2"]
    merged = merged_steer((segment("one", "r1"), segment("two", "r2")))
    assert merged.content == "one\n\ntwo" and merged.rendered_digest == sha256_digest("one\n\ntwo")


def test_deep_agents_declares_the_gentle_steer() -> None:
    assert LANE_COMMAND_SEMANTICS["interrupt_and_inject"]["deep_agents"] == "cooperative_inject"
    assert DEEP_AGENTS_DESCRIBE.delivery_semantics["interrupt_and_inject"] == "cooperative_inject"
    from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter

    assert issubclass(DeepAgentRuntimeAdapter, SteerFollowUpLane)
