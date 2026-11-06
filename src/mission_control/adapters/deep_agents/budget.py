"""Turn stops: Mission Control answers instead of the model inside a Deep Agents turn.

Two middlewares end a turn at the next model call (tracing Stage 2, F-S2-7 and F-S2-9):

- `BudgetStopMiddleware` enforces the operation's Budget. The kernel checks an operation's
  usage against its immutable `budget_limits` when the attempt settles
  (`operation_execution._validate_bound_usage`: `failed/budget_exceeded`), so a turn that
  crosses its reservation would keep calling the model until it ends on its own. The
  middleware checks before every model call what the invocation has already spent, read from
  the same chat-model observer the settlement charges (parent and in-process children,
  provider-reported tokens, plus what the resumed lineage already spent), and ends the turn
  once a bounded dimension (`tokens.total`, `model.turns`) is exceeded: the overrun is at
  most the one call (or one child task) that crossed it, and the attempt settles
  `budget_exceeded` as before. Reaching a limit exactly is within budget
  (`_validate_bound_usage` compares with `>`), so the turn continues until a call takes it
  over. W1 D41: the limits are the tighter of the operation's reservation and what the
  authored run budget leaves (`adapter._turn_limits`), and `tool.calls.total` is bounded
  too: a tool call past it is refused before it runs (a `ToolMessage(status="error")`
  marked `mc_budget_stop`), and the next model call is answered by the stop.
- `FenceStopMiddleware` ends the turn once the run generation is behind a Stop Fence.

Both wrap the model call (`wrap_model_call`) rather than adding a `before_model` hook, so the
graph keeps its nodes and its step numbering (the checkpoints and points of every turn). The
answer is an `AIMessage` without tool calls, marked in `additional_kwargs` (`mc_budget_stop`,
`mc_fence_stop`; a hook's DENY answer is marked `mc_hook_stop`), which ends the agent run; it
carries no usage and `is_turn_stop` keeps it out of the operation's model turns.

deepagents places custom middleware after its core stack, i.e. inside its summarization
middleware, so the Mission summarization middleware runs the same checks before it would
summarize (Tracing Stage 3, R3-F2): `first_turn_stop` / `first_turn_stop_sync`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

logger = logging.getLogger(__name__)

BUDGET_STOP = "mc_budget_stop"
FENCE_STOP = "mc_fence_stop"
HOOK_STOP = "mc_hook_stop"
TURN_STOP_MARKERS = (BUDGET_STOP, FENCE_STOP, HOOK_STOP)
BOUNDED_DIMENSIONS = ("tokens.total", "model.turns", "tool.calls.total")
TOOL_CALLS = "tool.calls.total"


def turn_stop_marker(message: BaseMessage) -> str | None:
    """The marker of a turn stop Mission Control answered instead of the model, or None."""

    if not isinstance(message, AIMessage):
        return None
    return _marker(message)


def refused_tool_call(message: BaseMessage) -> bool:
    """A tool call Mission Control refused before it ran (an exhausted budget or a hook's
    DENY): never a tool call the operation spent."""

    return isinstance(message, ToolMessage) and _marker(message) is not None


def _marker(message: BaseMessage) -> str | None:
    kwargs = message.additional_kwargs or {}
    return next((marker for marker in TURN_STOP_MARKERS if marker in kwargs), None)


def is_turn_stop(message: BaseMessage) -> bool:
    """A turn stop Mission Control answered instead of the model (budget, fence or hook)."""

    return turn_stop_marker(message) is not None


class TurnStop(Protocol):
    """A check that may answer a model call instead of the model."""

    async def turn_stop(self) -> AIMessage | None: ...

    def turn_stop_sync(self) -> AIMessage | None: ...


async def first_turn_stop(stops: Sequence[TurnStop]) -> AIMessage | None:
    """The first stop that answers, in order; None lets the model call proceed."""

    for stop in stops:
        message = await stop.turn_stop()
        if message is not None:
            return message
    return None


def first_turn_stop_sync(stops: Sequence[TurnStop]) -> AIMessage | None:
    for stop in stops:
        message = stop.turn_stop_sync()
        if message is not None:
            return message
    return None


class FenceStopMiddleware(AgentMiddleware[Any, Any, Any]):
    """End the turn at the next model call once the run is stop-fenced (tracing Stage 2,
    F-S2-9). The kernel fence hook denies the next gated tool call, but without this the
    model was still called once more after the denial (live FX-TR-CANCEL-LIVE)."""

    def __init__(self, fenced: Callable[[], Awaitable[str | None]]) -> None:
        super().__init__()
        self._fenced = fenced

    @property
    def name(self) -> str:
        return "BellLabsFenceStop"

    async def turn_stop(self) -> AIMessage | None:
        try:
            reason = await self._fenced()
        except Exception:
            # Tracing Stage 3 (R1-F11): a fence that cannot be read fails open; the kernel
            # fence hook still gates every effect, and the cancel path still settles.
            logger.warning(
                "the stop fence could not be read; the model call proceeds", exc_info=True
            )
            return None
        if reason is None:
            return None
        return AIMessage(
            content=f"Mission Control ended this turn: {reason}.",
            additional_kwargs={FENCE_STOP: {"reason": reason}},
        )

    def turn_stop_sync(self) -> AIMessage | None:
        # Imported here: the hook module imports this one for the stop markers.
        from mission_control.adapters.deep_agents.hooks import _run_coroutine

        return _run_coroutine(self.turn_stop)

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        # Tracing Stage 3 (R3-F12): the sync path (the base class raises without it).
        stop = self.turn_stop_sync()
        return stop if stop is not None else handler(request)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        stop = await self.turn_stop()
        return stop if stop is not None else await handler(request)


class BudgetStopMiddleware(AgentMiddleware[Any, Any, Any]):
    """End the turn before the next model call once the operation's budget is exceeded, and
    refuse a tool call that would exceed `tool.calls.total` before it runs (W1 D41).

    `admit_tool_call(tool_call_id, limit)` admits one tool call against everything the
    invocation already spent (the adapter's `_TurnSpend.admit`); without it the middleware
    counts the calls it admitted itself."""

    def __init__(
        self,
        limits: Mapping[str, int],
        spent: Callable[[], Mapping[str, int]],
        *,
        admit_tool_call: Callable[[str, int], bool] | None = None,
    ) -> None:
        super().__init__()
        self._limits = {
            dimension: int(limits[dimension])
            for dimension in BOUNDED_DIMENSIONS
            if dimension in limits
        }
        self._spent = spent
        self._admit = admit_tool_call or self._admit_locally
        self._admitted: set[str] = set()
        self._refused = 0

    @property
    def name(self) -> str:
        return "BellLabsBudgetStop"

    def exhausted(self) -> dict[str, dict[str, int]]:
        spent = dict(self._spent())
        if self._refused:
            # A refused call is one past the cap: the dimension is exhausted.
            spent[TOOL_CALLS] = int(spent.get(TOOL_CALLS, 0)) + self._refused
        return {
            dimension: {"limit": limit, "spent": int(spent.get(dimension, 0))}
            for dimension, limit in self._limits.items()
            if int(spent.get(dimension, 0)) > limit
        }

    def _admit_locally(self, tool_call_id: str, limit: int) -> bool:
        if tool_call_id not in self._admitted and len(self._admitted) >= limit:
            return False
        self._admitted.add(tool_call_id)
        return True

    def refusal(self, tool_call: Mapping[str, Any]) -> ToolMessage | None:
        """The answer to a tool call past `tool.calls.total`, or None to run it."""

        limit = self._limits.get(TOOL_CALLS)
        if limit is None:
            return None
        if self._admit(str(tool_call.get("id") or ""), limit):
            return None
        self._refused += 1
        return ToolMessage(
            content=(
                "Mission Control refused this tool call: the operation budget is exhausted "
                f"({TOOL_CALLS}). Do not call more tools."
            ),
            tool_call_id=str(tool_call.get("id", "")),
            name=str(tool_call.get("name", "")),
            status="error",
            additional_kwargs={BUDGET_STOP: self.exhausted()},
        )

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        refused = self.refusal(request.tool_call)
        return refused if refused is not None else handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        refused = self.refusal(request.tool_call)
        return refused if refused is not None else await handler(request)

    def stop_message(self) -> AIMessage | None:
        exhausted = self.exhausted()
        if not exhausted:
            return None
        names = ", ".join(sorted(exhausted))
        return AIMessage(
            content=(
                f"Mission Control ended this turn: the operation budget is exhausted ({names})."
            ),
            additional_kwargs={BUDGET_STOP: exhausted},
        )

    async def turn_stop(self) -> AIMessage | None:
        return self.stop_message()

    def turn_stop_sync(self) -> AIMessage | None:
        return self.stop_message()

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        stop = self.stop_message()
        return stop if stop is not None else handler(request)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        stop = self.stop_message()
        return stop if stop is not None else await handler(request)
