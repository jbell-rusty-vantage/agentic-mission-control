"""Builders, constants and fakes that other test files import.

Moved from tests/unit/agent_server/test_async_subagent_server_offline.py.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage

from tests.support.models import ScriptedChatModel


def pong(messages: list[BaseMessage], call: int) -> AIMessage:
    del messages, call
    return AIMessage(
        content="PONG", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    )


def scripted_child_model() -> ScriptedChatModel:
    """The hosted child's cognition: it answers PONG to every call."""

    return ScriptedChatModel(script=pong, label="rrm-013-scripted-child")
