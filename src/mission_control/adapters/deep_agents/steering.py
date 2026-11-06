"""Gentle steering of a running Deep Agents turn (`cooperative_inject`, owner 2026-11-06).

The owner's two intervention kinds are *queue context* (delivered at the next boundary) and
*steer with context* (delivered into the running turn, a gentle injection preferred over
interrupt and inject). Deep Agents runs its turn in the worker process, so a steer needs no
cancel: `InterruptAndInjectService` hands the injected segment to the lane (`inject`), the
lane puts it in this process-local inbox under the operation binding, and
`OperatorSteerMiddleware` drains it at the next model call, adding one human message to
that call's input and to the LangGraph state in the same step. The message is therefore
checkpointed (a cognition point records it) and the turn continues with its tools, files and
budget intact.

A segment the turn never drains (the turn ended after its last model call) is returned by
`close` and run as a follow-up turn by the inject service, so no steer is lost.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Final

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelResponse,
)
from langchain_core.messages import HumanMessage

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import PromptSegment

STEER_KWARG: Final = "mc_operator_steer"
STEER_PREAMBLE: Final = (
    "Operator steer from the mission operator, delivered while you work. Apply it to the "
    "work in progress and continue; do not restart completed steps. It never changes "
    "budgets, permissions or acceptance."
)


@dataclass(frozen=True)
class SteerItem:
    delivery_key: str
    segment: PromptSegment

    @property
    def message_id(self) -> str:
        return "operator-steer:" + sha256_digest(self.delivery_key)[7:]

    def message(self) -> HumanMessage:
        return HumanMessage(
            content=f"{STEER_PREAMBLE}\n\n{self.segment.content}",
            id=self.message_id,
            additional_kwargs={
                STEER_KWARG: {
                    "delivery_key": self.delivery_key,
                    "source_ref": self.segment.source_ref,
                    "rendered_digest": self.segment.rendered_digest,
                }
            },
        )


class SteerInbox:
    """Process-local steer queues, one per running operation binding (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict[str, list[SteerItem]] = {}

    def open(self, key: str) -> None:
        with self._lock:
            self._open.setdefault(key, [])

    def is_open(self, key: str) -> bool:
        with self._lock:
            return key in self._open

    def put(self, key: str, item: SteerItem) -> bool:
        """Queue a steer for a running turn; False when no turn of `key` is running."""

        with self._lock:
            queue = self._open.get(key)
            if queue is None:
                return False
            if all(existing.delivery_key != item.delivery_key for existing in queue):
                queue.append(item)
            return True

    def take(self, key: str) -> list[SteerItem]:
        with self._lock:
            queue = self._open.get(key)
            if not queue:
                return []
            taken, queue[:] = list(queue), []
            return taken

    def close(self, key: str) -> list[SteerItem]:
        """End the turn's inbox; the steers it never drained, for a follow-up turn."""

        with self._lock:
            return self._open.pop(key, [])


class OperatorSteerMiddleware(AgentMiddleware[Any, Any, Any]):
    """Add pending operator steers to the next model call and to the thread state.

    Implemented as `wrap_model_call`, not `before_model`: a `before_model` hook is one more
    graph node, so every model call would write one more checkpoint (and cognition point).
    Here the steer joins the request the model sees and leads the model node's `result`,
    so it is appended to `messages` (and checkpointed) in the same step as the reply.
    """

    def __init__(self, inbox: SteerInbox, key: str) -> None:
        super().__init__()
        self._inbox = inbox
        self._key = key

    @property
    def name(self) -> str:
        return "BellLabsOperatorSteer"

    def _pending(self, request: Any) -> list[HumanMessage]:
        items = self._inbox.take(self._key)
        if not items:
            return []
        present = {getattr(message, "id", None) for message in getattr(request, "messages", [])}
        return [item.message() for item in items if item.message_id not in present]

    @staticmethod
    def _with_steers(steers: list[HumanMessage], response: Any) -> Any:
        if isinstance(response, ExtendedModelResponse):
            return replace(
                response,
                model_response=OperatorSteerMiddleware._with_steers(
                    steers, response.model_response
                ),
            )
        if isinstance(response, ModelResponse):
            return ModelResponse(
                result=[*steers, *response.result],
                structured_response=response.structured_response,
            )
        return ModelResponse(result=[*steers, response])

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        steers = self._pending(request)
        if not steers:
            return handler(request)
        response = handler(request.override(messages=[*request.messages, *steers]))
        return self._with_steers(steers, response)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        steers = self._pending(request)
        if not steers:
            return await handler(request)
        response = await handler(request.override(messages=[*request.messages, *steers]))
        return self._with_steers(steers, response)


__all__ = [
    "STEER_KWARG",
    "STEER_PREAMBLE",
    "OperatorSteerMiddleware",
    "SteerInbox",
    "SteerItem",
]
