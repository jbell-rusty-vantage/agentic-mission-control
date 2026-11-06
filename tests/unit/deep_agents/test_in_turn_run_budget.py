"""W1 D41 / D38 (session 12): the authored run budget holds inside a Deep Agents turn.

Live run f243e3d8: a Goal Loop verifier made 69 model calls and 71 tool calls against a run
budget of `tool_calls: 20`, `tokens: 300000`, and the ledger recorded 0 consumed. A Goal Loop
iteration reserves only `goal.iterations`, and the lane both stopped and reported usage on
the reservation's dimensions only. Now the turn carries the run's in-turn dimensions and what
the run's hard caps leave (`RuntimeInvocation.run_budget_*`): its model calls, tool calls and
tokens are reported on them, and the turn stops once a dimension would be exceeded. A tool
call past the cap is refused before it runs; the next model call is answered by the stop.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from mission_control.adapters.deep_agents.adapter import (
    _budget_stop_of,
    _ModelCallObserver,
    _turn_limits,
    _TurnSpend,
    _usage,
)
from mission_control.adapters.deep_agents.budget import (
    BUDGET_STOP,
    BudgetStopMiddleware,
    turn_stop_marker,
)

USAGE = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
RUN_DIMENSIONS = ("model.turns", "tokens.total", "tool.calls.total")

executed: list[str] = []


@tool
def note(text: str) -> str:
    """Record a note."""

    executed.append(text)
    return f"noted {text}"


class AlwaysCallsTools(BaseChatModel):
    """A verifier that never decides: every answer asks for one more tool call."""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "always-calls-tools"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> AlwaysCallsTools:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        self.calls += 1
        if self.calls > 50:
            raise RuntimeError("the turn is unbounded")
        message = AIMessage(
            content="",
            id=f"a-{self.calls}",
            tool_calls=[
                {"name": "note", "args": {"text": str(self.calls)}, "id": f"t{self.calls}"}
            ],
            usage_metadata=dict(USAGE),  # type: ignore[arg-type]
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def _invocation(
    limits: dict[str, int],
    *,
    dimensions: Sequence[str] = RUN_DIMENSIONS,
    remaining: dict[str, int] | None = None,
) -> Any:
    return SimpleNamespace(
        binding=SimpleNamespace(budget_limits=limits),
        run_budget_dimensions=tuple(dimensions),
        run_budget_remaining=dict(remaining or {}),
    )


@pytest.mark.asyncio
async def test_a_turn_that_keeps_calling_tools_stops_at_the_run_tool_call_budget() -> None:
    executed.clear()
    model = AlwaysCallsTools()
    invocation = _invocation({"goal.iterations": 1}, remaining={"tool.calls.total": 3})
    calls = _ModelCallObserver()
    spend = _TurnSpend(calls)
    budget = BudgetStopMiddleware(_turn_limits(invocation), spend, admit_tool_call=spend.admit)
    agent = create_agent(model, tools=[note], middleware=[budget])

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="verify")]}, config={"callbacks": [calls]}
    )

    messages = result["messages"]
    # Three tool calls ran; the fourth was refused before it ran; the fifth model call was
    # answered by the stop.
    assert executed == ["1", "2", "3"]
    assert model.calls == 4
    refused = [
        message
        for message in messages
        if isinstance(message, ToolMessage) and BUDGET_STOP in message.additional_kwargs
    ]
    assert len(refused) == 1 and refused[0].status == "error"
    assert refused[0].tool_call_id == "t4"
    final = messages[-1]
    assert turn_stop_marker(final) == BUDGET_STOP and not final.tool_calls
    stop = {"tool.calls.total": {"limit": 3, "spent": 4}}
    assert final.additional_kwargs[BUDGET_STOP] == stop
    # The typed stop the settlement reads, and the usage it charges (refused calls never ran).
    assert _budget_stop_of(messages) == stop
    assert _usage(invocation, messages).amounts == {
        "model.turns": 4,
        "tokens.total": 200,
        "tool.calls.total": 3,
    }
    assert spend()["tool.calls.total"] == 3


@pytest.mark.asyncio
async def test_a_turn_stops_past_the_runs_remaining_tokens() -> None:
    executed.clear()
    model = AlwaysCallsTools()
    invocation = _invocation({"goal.iterations": 1}, remaining={"tokens.total": 120})
    calls = _ModelCallObserver()
    spend = _TurnSpend(calls)
    budget = BudgetStopMiddleware(_turn_limits(invocation), spend, admit_tool_call=spend.admit)
    agent = create_agent(model, tools=[note], middleware=[budget])

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="verify")]}, config={"callbacks": [calls]}
    )

    assert model.calls == 3  # 50, 100, 150 > 120
    assert _budget_stop_of(result["messages"]) == {"tokens.total": {"limit": 120, "spent": 150}}


def test_turn_limits_are_the_tighter_of_the_reservation_and_the_run_budget() -> None:
    invocation = _invocation(
        {"tokens.total": 500, "goal.iterations": 1, "model.turns": 4},
        remaining={"tokens.total": 300, "tool.calls.total": 20},
    )
    assert _turn_limits(invocation) == {
        "model.turns": 4,
        "tokens.total": 300,
        "tool.calls.total": 20,
    }
    assert _turn_limits(_invocation({"goal.iterations": 1}, dimensions=())) == {}


def test_usage_is_reported_on_the_runs_dimensions_beyond_the_reservation() -> None:
    """D38: a Goal Loop iteration reserves `goal.iterations` only; its turn's spend is still
    reported on the run's in-turn dimensions, and only on dimensions the run declares."""

    messages: list[BaseMessage] = [
        HumanMessage(content="go", id="h-1"),
        AIMessage(
            content="",
            id="a-1",
            tool_calls=[{"name": "note", "args": {"text": "x"}, "id": "t1"}],
            usage_metadata=dict(USAGE),  # type: ignore[arg-type]
        ),
        ToolMessage(content="noted x", tool_call_id="t1", id="m-1"),
        AIMessage(content="done", id="a-2", usage_metadata=dict(USAGE)),  # type: ignore[arg-type]
    ]
    assert _usage(_invocation({"goal.iterations": 1}), messages).amounts == {
        "model.turns": 2,
        "tokens.total": 100,
        "tool.calls.total": 1,
    }
    only_tokens = _invocation({"goal.iterations": 1}, dimensions=("tokens.total",))
    assert _usage(only_tokens, messages).amounts == {"tokens.total": 100}
    unbudgeted = _invocation({"goal.iterations": 1}, dimensions=())
    assert _usage(unbudgeted, messages).amounts == {}
    assert _budget_stop_of(messages) == {}
