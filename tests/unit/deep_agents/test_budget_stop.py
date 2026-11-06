"""Tracing Stage 2 (F-S2-7): the operation budget ends a Deep Agents turn past the cap.

The middleware reads what the invocation has spent (the chat-model observer the settlement
charges) when the agent calls its model, and answers instead of the model once `tokens.total`
or `model.turns` is exceeded; reaching a limit exactly is within budget. An agent built with
it stops calling its model after the call that crossed the cap, with no extra graph node.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from mission_control.adapters.deep_agents.budget import (
    BUDGET_STOP,
    BudgetStopMiddleware,
    is_turn_stop,
)


def test_the_stop_names_the_exceeded_dimension_only_past_the_cap() -> None:
    spent = {"tokens.total": 0, "model.turns": 0}
    middleware = BudgetStopMiddleware({"tokens.total": 100, "model.turns": 9}, lambda: spent)
    assert middleware.stop_message() is None
    spent["tokens.total"] = 100  # reaching the limit is within budget
    assert middleware.stop_message() is None
    spent["tokens.total"] = 101
    message = middleware.stop_message()
    assert message is not None and is_turn_stop(message) and not message.tool_calls
    assert message.additional_kwargs[BUDGET_STOP] == {"tokens.total": {"limit": 100, "spent": 101}}


def test_an_unbounded_operation_never_stops() -> None:
    middleware = BudgetStopMiddleware({}, lambda: {"tokens.total": 10**9})
    assert middleware.stop_message() is None


class ToolModel(GenericFakeChatModel):
    """The fake chat model, accepting the agent's tool binding and counting its calls."""

    calls: int = 0

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        del tools, kwargs
        return self

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return await super()._agenerate(*args, **kwargs)


@tool
def note(text: str) -> str:
    """Record a note."""

    return f"noted {text}"


@pytest.mark.asyncio
async def test_an_agent_stops_calling_its_model_past_the_cap() -> None:
    def answer(index: int) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[{"name": "note", "args": {"text": str(index)}, "id": f"c{index}"}],
            usage_metadata={"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
        )

    model = ToolModel(messages=iter([answer(index) for index in range(10)]))

    def spent() -> dict[str, Any]:
        return {"tokens.total": 50 * model.calls, "model.turns": model.calls}

    agent = create_agent(
        model, tools=[note], middleware=[BudgetStopMiddleware({"tokens.total": 120}, spent)]
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "go"}]})
    assert model.calls == 3  # 50, 100, 150: the third call crossed the 120-token cap
    assert is_turn_stop(result["messages"][-1])
