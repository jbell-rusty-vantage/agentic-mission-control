"""Builders, constants and fakes that other test files import.

Moved from tests/unit/agent_server/test_async_subagent_server_offline.py.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChildModel(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "rrm-013-scripted-child"

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> BaseChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        self.calls += 1
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="PONG",
                        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                    )
                )
            ]
        )
