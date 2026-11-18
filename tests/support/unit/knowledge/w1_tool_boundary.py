"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_w1_tool_boundary.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from tests.support.knowledge.gateway import Lane


async def _calls(h: Lane, *calls: tuple[str, dict[str, Any], str]) -> list[dict[str, Any]]:
    token = CURRENT_INVOCATION.set(h.live())
    try:
        return [await h.call(name, args, call_id) for name, args, call_id in calls]
    finally:
        CURRENT_INVOCATION.reset(token)
