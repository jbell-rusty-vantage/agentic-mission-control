"""The one LLM double: `ScriptedChatModel`.

The chat model is the main external boundary of a Deep Agents run. With it scripted, the real
`create_deep_agent` graph, its tools, the checkpointer and the harness run without spend.

A script is data: a callable `(messages, call) -> AIMessage` (or an awaitable of one), where
`messages` is the batch the model was called with and `call` counts from 1. The model:

- records every input batch (`seen`) and a `(humans, tools)` summary of it (`calls`);
- records what each `bind_tools` bound (`bound`) and returns itself, so the record is shared;
- gives each answer a stable id and, unless the script set one, default `usage_metadata`;
- refuses to run past `max_calls` (a loop guard);
- answers on the sync and the async path, and keeps the fault hooks of the RRM-004 harness:
  `before_call` (an async hook before a call), `fail_on` (a provider exception on a call) and
  `gate_on` (a call that blocks until released, to model a slow holder).

A script that needs per-invocation data (a run id, a shared log) is a closure over it.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from hashlib import sha256
from typing import Any, NamedTuple

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr

type Script = Callable[[list[BaseMessage], int], AIMessage | Awaitable[AIMessage]]

DEFAULT_USAGE: dict[str, int] = {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}


class Call(NamedTuple):
    """What one model call observed: its human messages and its tool results."""

    humans: int
    tools: int


class ScriptedChatModel(BaseChatModel):
    """A chat model that answers from its `script`; see the module docstring."""

    script: Any
    label: str = "scripted"
    usage: dict[str, int] | None = DEFAULT_USAGE
    max_calls: int = 50

    _seen: list[list[BaseMessage]] = PrivateAttr(default_factory=list)
    _calls: list[Call] = PrivateAttr(default_factory=list)
    _bound: list[dict[str, Any]] = PrivateAttr(default_factory=list)
    _fail_on: dict[int, BaseException] = PrivateAttr(default_factory=dict)
    _before: dict[int, Callable[[], Awaitable[None]]] = PrivateAttr(default_factory=dict)
    _gate_on: int | None = PrivateAttr(default=None)
    _gate: asyncio.Event | None = PrivateAttr(default=None)
    _gate_entered: asyncio.Event | None = PrivateAttr(default=None)

    @classmethod
    def from_messages(cls, messages: Iterable[AIMessage], **fields: Any) -> ScriptedChatModel:
        """A fixed script: the given answers, in order; a call past the last one fails."""

        answers = list(messages)

        def script(_messages: list[BaseMessage], call: int) -> AIMessage:
            if call > len(answers):
                raise RuntimeError(f"the fixed script has only {len(answers)} answers")
            return answers[call - 1]

        return cls(script=script, **fields)

    @property
    def _llm_type(self) -> str:
        return self.label

    @property
    def seen(self) -> list[list[BaseMessage]]:
        """Every input batch, in call order."""

        return self._seen

    @property
    def calls(self) -> list[Call]:
        """One `(humans, tools)` summary per call, in call order."""

        return self._calls

    @property
    def bound(self) -> list[dict[str, Any]]:
        """One `{"tools": [names], **kwargs}` entry per `bind_tools`."""

        return self._bound

    def before_call(self, call: int, hook: Callable[[], Awaitable[None]]) -> None:
        """Await `hook` before the given (async) call is observed."""

        self._before[call] = hook

    def fail_on(self, call: int, error: BaseException) -> None:
        """An ordinary provider exception (not a worker loss) on the given call."""

        self._fail_on[call] = error

    def gate_on(self, call: int) -> tuple[asyncio.Event, asyncio.Event]:
        """Block the given (async) call until released: returns `(entered, release)`."""

        self._gate_on = call
        self._gate = asyncio.Event()
        self._gate_entered = asyncio.Event()
        return self._gate_entered, self._gate

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict[str, Any] | type | Any],
        **kwargs: Any,
    ) -> ScriptedChatModel:
        self._bound.append({"tools": [getattr(tool, "name", tool) for tool in tools], **kwargs})
        return self

    def _observe(self, messages: list[BaseMessage]) -> int:
        index = len(self._calls) + 1
        if index > self.max_calls:
            raise RuntimeError(f"{self.label}: the scripted model looped past {self.max_calls}")
        self._seen.append(list(messages))
        self._calls.append(
            Call(
                humans=sum(message.type == "human" for message in messages),
                tools=sum(isinstance(message, ToolMessage) for message in messages),
            )
        )
        if index in self._fail_on:
            raise self._fail_on[index]
        return index

    def _result(self, messages: list[BaseMessage], index: int, message: AIMessage) -> ChatResult:
        update: dict[str, Any] = {}
        if not message.id:
            update["id"] = f"{self.label}-{index}-{_batch_digest(messages)}"
        if message.usage_metadata is None and self.usage is not None:
            update["usage_metadata"] = dict(self.usage)
        answer = message.model_copy(update=update) if update else message
        return ChatResult(generations=[ChatGeneration(message=answer)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        index = self._observe(messages)
        message = self.script(messages, index)
        if inspect.isawaitable(message):
            if inspect.iscoroutine(message):
                message.close()
            raise TypeError(f"{self.label}: an async script cannot answer a sync call")
        return self._result(messages, index, message)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        hook = self._before.get(len(self._calls) + 1)
        if hook is not None:
            await hook()
        index = self._observe(messages)
        if index == self._gate_on:
            assert self._gate is not None and self._gate_entered is not None
            self._gate_entered.set()
            await self._gate.wait()
        message = self.script(messages, index)
        if inspect.isawaitable(message):
            message = await message
        return self._result(messages, index, message)


def _batch_digest(messages: Sequence[BaseMessage]) -> str:
    """A digest of what a batch says (not of its message ids, which may be random)."""

    rows = [
        [
            message.type,
            message.content,
            [[call["name"], call["args"]] for call in getattr(message, "tool_calls", None) or ()],
            getattr(message, "tool_call_id", None),
        ]
        for message in messages
    ]
    return sha256(json.dumps(rows, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


# --- Script helpers ---------------------------------------------------------------------------


def tool_call(name: str, args: dict[str, Any], call_id: str, **fields: Any) -> AIMessage:
    """An answer that calls one tool."""

    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
        **fields,
    )


def tool_messages(messages: Sequence[BaseMessage]) -> list[ToolMessage]:
    return [message for message in messages if isinstance(message, ToolMessage)]


def since_latest_input(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """The messages from the latest human message on (the operation's own input)."""

    humans = [index for index, message in enumerate(messages) if message.type == "human"]
    return list(messages[humans[-1] :]) if humans else list(messages)
