"""Tracing Stage 3: the turn stops (budget, Stop Fence, hook DENY) end a turn everywhere.

- R3-F2: deepagents splices Mission Control's middleware after its core stack, i.e. inside
  the summarization slot, so past the cap or behind the fence the summarizer checks the
  stops before it would make its own paid call.
- Sync-child stops: a running child is stopped by the parent's budget and fence too.
- R3-F4: the budget reads what a resumed lineage already spent.
- R3-F9 / R3-F10: a stop is never a model call (usage, provider run id), and a hook's DENY
  answer is marked like the other stops.
- R3-F12 / R1-F11: the fence stop has a sync path and fails open when the fence is unread.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from deepagents.backends import StateBackend
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from mission_control.adapters.deep_agents.adapter import (
    _compile,
    _message_usage,
    _ModelCallObserver,
    _provider_run_id,
    _subagent_specs,
    _TurnSpend,
    _usage,
)
from mission_control.adapters.deep_agents.budget import (
    BUDGET_STOP,
    FENCE_STOP,
    HOOK_STOP,
    BudgetStopMiddleware,
    FenceStopMiddleware,
    is_turn_stop,
    turn_stop_marker,
)
from mission_control.adapters.deep_agents.compaction import (
    ObservedSummarizationMiddleware,
    StopGuardedSummarizationMiddleware,
)
from mission_control.adapters.deep_agents.hooks import _stopped

USAGE = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}


class Scripted(BaseChatModel):
    """A chat model answering from `respond(messages, call)`; it counts its calls."""

    respond: Any
    label: str = "model"
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return f"scripted-turn-stops-{self.label}"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Scripted:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.calls += 1
        if self.calls > 20:
            raise RuntimeError("scripted model looped")
        message = self.respond(messages, self.calls)
        message.id = message.id or f"{self.label}-{self.calls}"
        return ChatResult(generations=[ChatGeneration(message=message)])


@tool
def note(text: str) -> str:
    """Record a note."""

    return f"noted {text}"


def _noting(prefix: str) -> Callable[[list[BaseMessage], int], AIMessage]:
    def respond(messages: list[BaseMessage], call: int) -> AIMessage:
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {"name": "note", "args": {"text": f"{prefix}{call}"}, "id": f"{prefix}{call}"}
            ],
            usage_metadata=dict(USAGE),  # type: ignore[arg-type]
        )

    return respond


def _summary(messages: list[BaseMessage], call: int) -> AIMessage:
    del messages, call
    return AIMessage(content="SUMMARY")


def _materialized(
    model: BaseChatModel,
    middleware: Sequence[Any],
    subagents: Sequence[dict[str, Any]] = (),
) -> Any:
    return SimpleNamespace(
        model=model,
        tools=(note,),
        middleware=tuple(middleware),
        subagents=tuple(subagents),
        skills=(),
        backend=StateBackend(),
        state_schema=None,
        context_schema=None,
        checkpointer=None,
        store=None,
        response_format=None,
    )


BINDING = SimpleNamespace(
    model=SimpleNamespace(provider="fixture-turn-stops"),
    skills=(),
    workspace=SimpleNamespace(read_mounts=(), exclusive_write_paths=("/outputs",)),
)


def _agent(
    model: BaseChatModel,
    summary_model: BaseChatModel,
    *,
    fence: FenceStopMiddleware,
    budget: BudgetStopMiddleware | None = None,
    subagents: Sequence[dict[str, Any]] = (),
) -> tuple[Any, StateBackend]:
    """The adapter's `_compile` over a materialization shaped like the materializer's: the
    fence stop first, then the observed summarizer (forced to summarize from 3 messages)."""

    materialized = _materialized(model, (), subagents)
    summarizer = ObservedSummarizationMiddleware.observed(
        summary_model, materialized.backend, trigger=("messages", 3), keep=("messages", 2)
    )
    materialized.middleware = (fence, summarizer)
    agent = _compile(
        materialized,
        BINDING,  # type: ignore[arg-type]
        system_prompt="Use the note tool.",
        extra_middleware=[budget] if budget is not None else [],
        name="belllabs-turn-stops",
    )
    return agent, materialized.backend


def _never_fenced() -> FenceStopMiddleware:
    async def fenced() -> str | None:
        return None

    return FenceStopMiddleware(fenced)


@pytest.mark.asyncio
async def test_past_the_cap_the_summarizer_makes_no_paid_call_before_the_stop() -> None:
    model = Scripted(respond=_noting("n"))
    summary = Scripted(respond=_summary, label="summary")
    calls = _ModelCallObserver()
    budget = BudgetStopMiddleware({"tokens.total": 40}, calls.spent)
    agent, _backend = _agent(model, summary, fence=_never_fenced(), budget=budget)

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="go")]}, config={"callbacks": [calls]}
    )

    # Call 1 spent 50 > 40; at call 2 the history (3 messages) would trigger summarization.
    assert model.calls == 1
    assert summary.calls == 0, "no summarization call after the cap"
    assert turn_stop_marker(result["messages"][-1]) == BUDGET_STOP


@pytest.mark.asyncio
async def test_behind_the_fence_the_summarizer_makes_no_paid_call_before_the_stop() -> None:
    model = Scripted(respond=_noting("n"))
    summary = Scripted(respond=_summary, label="summary")

    async def fenced() -> str | None:
        return "run is stop-fenced" if model.calls >= 1 else None

    agent, _backend = _agent(model, summary, fence=FenceStopMiddleware(fenced))

    result = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    assert model.calls == 1 and summary.calls == 0
    assert turn_stop_marker(result["messages"][-1]) == FENCE_STOP


@pytest.mark.asyncio
async def test_a_running_sync_child_is_stopped_past_the_cap_inside_the_child() -> None:
    def parent(messages: list[BaseMessage], call: int) -> AIMessage:
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "task",
                    "args": {"description": "Write notes.", "subagent_type": "writer"},
                    "id": f"task-{call}",
                }
            ],
            usage_metadata=dict(USAGE),  # type: ignore[arg-type]
        )

    model = Scripted(respond=parent, label="parent")
    child = Scripted(respond=_noting("c"), label="child")
    summary = Scripted(respond=_summary, label="summary")
    calls = _ModelCallObserver()
    budget = BudgetStopMiddleware({"tokens.total": 120}, calls.spent)
    spec = {
        "name": "writer",
        "description": "Writes notes.",
        "system_prompt": "Write notes.",
        "model": child,
        "tools": [note],
    }
    agent, _backend = _agent(model, summary, fence=_never_fenced(), budget=budget, subagents=[spec])

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="go")]}, config={"callbacks": [calls]}
    )

    # parent 50, child 100, child 150 > 120: the child's third call is answered by the stop
    # inside the child, and the parent's next call by the parent's.
    assert (model.calls, child.calls) == (1, 2)
    task_result = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    assert "operation budget is exhausted" in str(task_result.content)
    assert turn_stop_marker(result["messages"][-1]) == BUDGET_STOP
    assert summary.calls == 0


def test_child_specs_carry_the_stops_and_a_stop_guarded_summarizer() -> None:
    child = Scripted(respond=_noting("c"), label="child")
    fence = _never_fenced()
    budget = BudgetStopMiddleware({"tokens.total": 1}, lambda: {"tokens.total": 0})
    materialized = _materialized(
        Scripted(respond=_noting("n")),
        (),
        [{"name": "writer", "description": "d", "system_prompt": "p", "model": child}],
    )
    (spec,) = _subagent_specs(materialized, [fence, budget])
    guard, *stops = spec["middleware"]  # type: ignore[typeddict-item]
    assert isinstance(guard, StopGuardedSummarizationMiddleware)
    assert guard.name == "SummarizationMiddleware"  # replaces the child's own in place
    assert guard.stops == (fence, budget)
    assert stops == [fence, budget]
    assert _subagent_specs(materialized)[0].get("middleware") is None


@pytest.mark.asyncio
async def test_the_child_summarizer_answers_with_the_stop_without_summarizing() -> None:
    child = Scripted(respond=_summary, label="child")
    budget = BudgetStopMiddleware({"tokens.total": 1}, lambda: {"tokens.total": 2})
    guard = StopGuardedSummarizationMiddleware.guarding(child, StateBackend(), [budget])
    handled: list[Any] = []

    async def handler(request: Any) -> Any:
        handled.append(request)
        return AIMessage(content="model")

    stop = await guard.awrap_model_call(SimpleNamespace(state={}, messages=[]), handler)
    assert turn_stop_marker(stop) == BUDGET_STOP and not handled and child.calls == 0
    assert turn_stop_marker(guard.wrap_model_call(SimpleNamespace(), handler)) == BUDGET_STOP


def test_the_budget_reads_what_the_resumed_lineage_already_spent() -> None:
    invocation = SimpleNamespace(
        binding=SimpleNamespace(budget_limits={"tokens.total": 120, "model.turns": 9}),
        run_budget_dimensions=(),
    )
    prior = [HumanMessage(content="prior", id="h-0"), AIMessage(content="a", id="a-0")]
    leaf = [
        *prior,
        HumanMessage(content="turn", id="h-1"),
        AIMessage(content="", id="a-1", usage_metadata=dict(USAGE)),  # type: ignore[arg-type]
        AIMessage(content="", id="a-2", usage_metadata=dict(USAGE)),  # type: ignore[arg-type]
        AIMessage(content="stopped", id="s-1", additional_kwargs={BUDGET_STOP: {}}),
    ]
    calls = _ModelCallObserver()
    spend = _TurnSpend(calls)
    budget = BudgetStopMiddleware(invocation.binding.budget_limits, spend)
    assert budget.stop_message() is None
    spend.resume_from(invocation, leaf, prior)  # type: ignore[arg-type]
    # The interrupted part's two calls (100 tokens, 2 turns; the stop is no turn) count.
    assert spend() == {"model.turns": 2, "tokens.total": 100, "tool.calls.total": 0}
    assert budget.stop_message() is None
    response = SimpleNamespace(
        generations=[
            [SimpleNamespace(message=AIMessage(content="", id="a-3", usage_metadata=dict(USAGE)))]
        ]  # type: ignore[arg-type]
    )
    calls.on_llm_end(response)
    assert spend() == {"model.turns": 3, "tokens.total": 150, "tool.calls.total": 0}
    stop = budget.stop_message()
    assert stop is not None
    assert stop.additional_kwargs[BUDGET_STOP] == {"tokens.total": {"limit": 120, "spent": 150}}


def test_a_stop_is_never_a_model_call() -> None:
    invocation = SimpleNamespace(
        binding=SimpleNamespace(budget_limits={"model.turns": 9}), run_budget_dimensions=()
    )
    answer = AIMessage(content="answer", id="a-1", usage_metadata=dict(USAGE))  # type: ignore[arg-type]
    budget_stop = AIMessage(content="stopped", id="s-1", additional_kwargs={BUDGET_STOP: {}})
    messages: list[BaseMessage] = [HumanMessage(content="go", id="h-1"), answer, budget_stop]
    assert _provider_run_id(messages) == "a-1"
    assert [call["message_id"] for call in _message_usage(messages)] == ["a-1"]
    assert _usage(invocation, messages).amounts == {"model.turns": 1}  # type: ignore[arg-type]
    # R3-F10: a hook's DENY answer is a stop too, and keeps a budget stop's marker.
    denied = _stopped("no")
    assert turn_stop_marker(denied) == HOOK_STOP and is_turn_stop(denied)
    replaced = _stopped("no", replacing=budget_stop)
    assert turn_stop_marker(replaced) == BUDGET_STOP and HOOK_STOP in replaced.additional_kwargs
    assert _usage(invocation, [answer, denied, replaced]).amounts == {"model.turns": 1}  # type: ignore[arg-type]
    assert _provider_run_id([HumanMessage(content="go"), denied]) is None


@pytest.mark.asyncio
async def test_the_fence_stop_has_a_sync_path_and_fails_open_when_unread() -> None:
    async def fenced() -> str | None:
        return "run is stop-fenced"

    async def unreadable() -> str | None:
        raise ConnectionError("fence store down")

    def handler(request: Any) -> AIMessage:
        del request
        return AIMessage(content="model")

    stop = FenceStopMiddleware(fenced).wrap_model_call(object(), handler)
    assert turn_stop_marker(stop) == FENCE_STOP
    assert FenceStopMiddleware(unreadable).wrap_model_call(object(), handler).content == "model"

    async def ahandler(request: Any) -> AIMessage:
        return handler(request)

    answered = await FenceStopMiddleware(unreadable).awrap_model_call(object(), ahandler)
    assert answered.content == "model"
