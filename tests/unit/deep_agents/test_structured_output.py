"""Tracing Stage 2 (F-S2-1): the lane keeps a structured response the model produced.

`create_agent` leaves the validated `response_format` instance in `structured_response` (a
pydantic model for a pydantic schema) and the final message carries the structured-output
tool call, not JSON text; the live Sol verifier answered this way and the lane recorded no
structured output.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from mission_control.adapters.deep_agents.adapter import (
    _structured_output,
    _structured_response_written,
)
from mission_control.adapters.deep_agents.budget import BudgetStopMiddleware, is_turn_stop
from mission_control.domain.programs.goal_directed_runtime import GoalVerifierObservation


def test_a_pydantic_structured_response_becomes_the_structured_output() -> None:
    observation = GoalVerifierObservation(
        decision="rejected",
        progress_made=False,
        findings=("no note was produced",),
        output_contract_ref="fixture-output",
    )

    structured = _structured_output(observation, "")

    assert isinstance(structured, dict)
    assert GoalVerifierObservation.model_validate(structured) == observation


def test_a_dict_or_json_text_is_unchanged_and_prose_is_none() -> None:
    assert _structured_output({"a": 1}, "") == {"a": 1}
    assert _structured_output(None, '{"b": 2}') == {"b": 2}
    assert _structured_output(None, "I wrote the note.") is None


# --- Tracing Stage 3 (R3-F1): only this lineage's structured answer is its answer ----------


class Verdict(BaseModel):
    met: bool


class _ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        del tools, kwargs
        return self


async def _turn(agent: Any, config: dict[str, Any], text: str) -> Any:
    """One turn on the shared thread; returns the result checkpoint's snapshot."""

    await agent.ainvoke({"messages": [{"role": "user", "content": text}]}, config)
    return await agent.aget_state(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["text", "budget_stop"])
async def test_a_later_turn_on_the_thread_does_not_return_the_earlier_verdict(
    ending: str,
) -> None:
    """Units of a session share the thread and `create_agent` never clears
    `structured_response`; a turn that ends in text or in a Mission Control stop must not
    report the previous turn's verdict as its own."""

    answers = [
        AIMessage(content="", tool_calls=[{"name": "Verdict", "args": {"met": True}, "id": "v1"}]),
        # A stopped turn 2 calls no model.
        *([AIMessage(content="plain text, no verdict")] if ending == "text" else []),
        AIMessage(content="", tool_calls=[{"name": "Verdict", "args": {"met": False}, "id": "v3"}]),
    ]
    model = _ToolModel(messages=iter(answers))
    spent = {"tokens.total": 0}
    saver = InMemorySaver()
    agent = create_agent(
        model,
        tools=[],
        response_format=ToolStrategy(Verdict),
        checkpointer=saver,
        middleware=[BudgetStopMiddleware({"tokens.total": 10}, lambda: spent)],
    )
    config: dict[str, Any] = {"configurable": {"thread_id": "session-thread"}}
    plan = SimpleNamespace(namespace="session-thread")

    first = await _turn(agent, config, "turn 1")
    assert await _structured_response_written(saver, plan, None, first.config)  # type: ignore[arg-type]
    first_key = SimpleNamespace(checkpoint_id=first.config["configurable"]["checkpoint_id"])

    if ending == "budget_stop":
        spent["tokens.total"] = 11
    second = await _turn(agent, config, "turn 2")
    # The stale verdict is still in the thread's values.
    assert second.values["structured_response"] == Verdict(met=True)
    assert not await _structured_response_written(saver, plan, first_key, second.config)  # type: ignore[arg-type]
    last = second.values["messages"][-1]
    assert is_turn_stop(last) is (ending == "budget_stop")
    assert _structured_output(None, str(last.content)) is None

    spent["tokens.total"] = 0
    second_key = SimpleNamespace(checkpoint_id=second.config["configurable"]["checkpoint_id"])
    third = await _turn(agent, config, "turn 3")
    assert await _structured_response_written(saver, plan, second_key, third.config)  # type: ignore[arg-type]
    assert _structured_output(third.values["structured_response"], "") == {"met": False}
