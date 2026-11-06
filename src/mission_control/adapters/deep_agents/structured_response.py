"""W1 D18: the ``tool_auto`` structured-response strategy.

Claude Sonnet 5.5 refuses forced tool choice (W1 D16) and refused the executor observation
schema as ``output_config.format`` with 400 "Schema is too complex." on every request (W1 run
457bd952): Anthropic compiles a constrained-decoding grammar from that schema, and beyond the
published limits (24 optional parameters, 16 union-typed parameters) an unpublished
compiled-grammar size limit applies
(https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

``tool_auto`` compiles no grammar: the schema is an ordinary (non-strict) tool the model calls
with ``tool_choice`` auto (LangChain ``ToolStrategy``, whose forced ``any`` choice
:func:`with_auto_tool_choice` turns into ``auto`` at bind time). The host enforces the
contract, append-only (no earlier message is ever edited, so preserved thinking holds):

- :func:`response_schema` validates the call against the full schema after parsing a JSON
  string given for an object-typed field exactly once, with the knowledge tools' strict rules
  (W1 D17, ``toolset.coerce_with_shapes``);
- :class:`RequireStructuredResponse` answers a response call made together with other tool
  calls with a refusal (the other calls run; the model answers again after their results),
  reminds a turn that ends without the call, and ends the turn without a result once
  :data:`MAX_ATTEMPTS` reminders and refused calls are spent in this invocation. A turn that
  ends without the call carries no structured output, which the node's missing-output handling
  refuses (terminal, never a silent success).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse, hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, model_validator

from mission_control.adapters.deep_agents.budget import is_turn_stop
from mission_control.application.knowledge.toolset import (
    ArgumentCoercionRefused,
    coerce_with_shapes,
    model_argument_shapes,
)

MAX_ATTEMPTS: Final = 3
MAX_REMINDERS: Final = MAX_ATTEMPTS  # kept name: reminders and refused calls share one bound
REMINDER_PREFIX: Final = "[mission-control] End this turn by calling the "
# The marker on every reminder and refused response call; its value scopes it to one
# invocation (the lineage stamp `belllabs_invocation_id`), so an interleaved message never
# resets the count and a later invocation on the same thread starts fresh.
ATTEMPT_MARKER: Final = "mc_response_attempt"
INVOCATION_STAMP: Final = "belllabs_invocation_id"
_AUTO_CLASSES: dict[type, type] = {}
_AUTO_FLAG: Final = "__mc_auto_tool_choice__"
_COERCING_FLAG: Final = "__mc_coercing_schema__"


def _forced(tool_choice: Any) -> bool:
    if isinstance(tool_choice, dict):
        return tool_choice.get("type") in {"any", "tool", "function", "required"}
    if isinstance(tool_choice, str):
        return tool_choice not in {"auto", "none"}
    return bool(tool_choice)


def _auto_bind_tools(
    self: Any, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any
) -> Any:
    parent: Any = type(self).__mro__[1]
    choice = "auto" if _forced(tool_choice) else tool_choice
    return parent.bind_tools(self, tools, tool_choice=choice, **kwargs)


def with_auto_tool_choice(model: BaseChatModel) -> BaseChatModel:
    """A copy of ``model`` whose ``bind_tools`` never forces a tool (``any``/named -> ``auto``).

    The copy's class is a subclass with one method overridden and no new field. It carries the
    parent's own name, qualified name and module, so the serialized identity (``lc_id``), the
    invocation parameters and everything the frames and digests record are the model's own."""

    cls = type(model)
    if getattr(cls, _AUTO_FLAG, False):
        return model
    auto = _AUTO_CLASSES.get(cls)
    if auto is None:
        auto = type(
            cls.__name__,
            (cls,),
            {
                "bind_tools": _auto_bind_tools,
                "__module__": cls.__module__,
                "__qualname__": cls.__qualname__,
                _AUTO_FLAG: True,
            },
        )
        _AUTO_CLASSES[cls] = auto
    copied = model.model_copy()
    copied.__class__ = auto
    return copied


def response_schema(schema: Any) -> Any:
    """The response tool's validation schema: ``schema`` itself, whose JSON Schema (the tool the
    model sees) is unchanged, with a before-validator that parses a JSON string given for an
    object-typed field exactly once (strict, bounded; ``ArgumentCoercionRefused`` otherwise,
    which ``ToolStrategy`` answers as a validation error). A non-pydantic schema is returned
    unchanged."""

    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        return schema
    shapes = model_argument_shapes(schema)
    if not shapes:
        return schema

    def coerce(cls: type[BaseModel], data: Any) -> Any:
        del cls
        if not isinstance(data, dict):
            return data
        try:
            coerced, _records = coerce_with_shapes(shapes, data)
        except ArgumentCoercionRefused as refused:
            raise ValueError(f"argument {refused.field}: {refused.reason}") from None
        return coerced

    return type(
        schema.__name__,
        (schema,),
        {
            "__module__": schema.__module__,
            "__qualname__": schema.__qualname__,
            "__doc__": schema.__doc__,
            "mc_coerce_json_strings": model_validator(mode="before")(coerce),
            _COERCING_FLAG: True,
        },
    )


def _scope() -> str:
    try:
        from langgraph.config import get_config

        metadata = get_config().get("metadata") or {}
    except RuntimeError:  # outside a graph run (direct calls in tests)
        return "unscoped"
    value = metadata.get(INVOCATION_STAMP)
    return str(value) if value is not None else "unscoped"


def _marked(message: BaseMessage, scope: str) -> bool:
    return (getattr(message, "additional_kwargs", None) or {}).get(ATTEMPT_MARKER) == scope


def _reminder(tool_names: Sequence[str], scope: str) -> HumanMessage:
    names = " or ".join(f"`{name}`" for name in tool_names)
    return HumanMessage(
        content=(
            f"{REMINDER_PREFIX}{names} tool exactly once with your final answer; a turn that "
            "ends without it records no result."
        ),
        additional_kwargs={ATTEMPT_MARKER: scope},
    )


class RequireStructuredResponse(AgentMiddleware[Any, Any, Any]):
    """Host enforcement of ``tool_auto`` (see the module doc)."""

    name = "mc_require_structured_response"

    def __init__(self, tool_names: Sequence[str], *, max_attempts: int = MAX_ATTEMPTS) -> None:
        super().__init__()
        self.tool_names = tuple(tool_names)
        self.max_attempts = max_attempts

    # -- the model step: a mixed turn, and refused calls, are marked (append-only) -----------

    def _checked(self, response: ModelResponse) -> ModelResponse:
        scope = _scope()
        ai = next((m for m in response.result if isinstance(m, AIMessage)), None)
        calls = ai.tool_calls if ai is not None else []
        others = [call for call in calls if call["name"] not in self.tool_names]
        result: list[BaseMessage] = []
        structured = response.structured_response
        for message in response.result:
            if not (isinstance(message, ToolMessage) and message.name in self.tool_names):
                result.append(message)
                continue
            if others:
                # S2: the other calls must run first; this response call is refused, never
                # accepted while their results are unseen.
                structured = None
                message = ToolMessage(
                    content=(
                        f"Refused: call `{message.name}` alone, in a later turn, after the "
                        "results of the other tool calls you made here."
                    ),
                    tool_call_id=message.tool_call_id,
                    # No tool name: LangChain ends the loop after a ToolMessage named like a
                    # structured-output tool, and the other calls' results must reach the model.
                    name=None,
                    status="error",
                    additional_kwargs={ATTEMPT_MARKER: scope},
                )
            elif structured is None:
                # A validation (or duplicate-call) refusal from ToolStrategy: one attempt.
                message = message.model_copy(
                    update={
                        "additional_kwargs": {**message.additional_kwargs, ATTEMPT_MARKER: scope}
                    }
                )
            result.append(message)
        if structured is not None and getattr(type(structured), _COERCING_FLAG, False):
            # The caller receives an instance of its own schema, not the coercing subclass.
            base: Any = type(structured).__mro__[1]
            structured = base.model_validate(structured.model_dump())
        return ModelResponse(result=result, structured_response=structured)

    def wrap_model_call(
        self, request: Any, handler: Callable[[Any], ModelResponse]
    ) -> ModelResponse:
        return self._checked(handler(request))

    async def awrap_model_call(
        self, request: Any, handler: Callable[[Any], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        return self._checked(await handler(request))

    # -- after the model step: remind, or end once the attempts are spent ---------------------

    def _decision(self, state: Any) -> dict[str, Any] | None:
        messages: list[BaseMessage] = list(state.get("messages") or ())
        if not messages:
            return None
        scope = _scope()
        attempts = sum(1 for message in messages if _marked(message, scope))
        last = messages[-1]
        if isinstance(last, ToolMessage):
            # A refused response call: the model tries again within the bound, then the turn
            # ends without a result.
            spent = _marked(last, scope) and attempts >= self.max_attempts
            return {"jump_to": "end"} if spent else None
        if not isinstance(last, AIMessage) or last.tool_calls or is_turn_stop(last):
            return None
        if attempts >= self.max_attempts:
            return None  # the turn ends without the call: the node refuses the missing output
        return {"messages": [_reminder(self.tool_names, scope)], "jump_to": "model"}

    @hook_config(can_jump_to=["model", "end"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        del runtime
        return self._decision(state)

    @hook_config(can_jump_to=["model", "end"])
    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        del runtime
        return self._decision(state)


__all__ = [
    "ATTEMPT_MARKER",
    "MAX_ATTEMPTS",
    "MAX_REMINDERS",
    "REMINDER_PREFIX",
    "RequireStructuredResponse",
    "response_schema",
    "with_auto_tool_choice",
]
