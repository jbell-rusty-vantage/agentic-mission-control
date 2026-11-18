"""Builders, constants and fakes that other test files import.

Moved from tests/integration/deep_agents/test_report_source_context.py.
"""

from __future__ import annotations

import re
from typing import ClassVar

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tests.support.integration.deep_agents.wi02_transfer_plan_lane import PlanReadingModel


class FullContextReader(PlanReadingModel):
    expected: ClassVar[bytes] = b""
    file_path: ClassVar[str] = ""
    observed: ClassVar[dict[int, str]] = {}

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        del stop, run_manager, kwargs
        results = [message for message in messages if isinstance(message, ToolMessage)]
        self.observed.clear()
        for result in results:
            for row in str(result.content).split("\n"):
                match = re.match(r"^\s*(\d+)(?:\.(\d+))?  (.*)$", row)
                if match:
                    line = int(match[1])
                    self.observed[line] = self.observed.get(line, "") + match[3]
        count = len(self.expected.decode().splitlines())
        if not results:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": self.file_path, "offset": offset, "limit": 150},
                        "id": f"read-{offset}",
                        "type": "tool_call",
                    }
                    for offset in range(0, count, 150)
                ],
            )
        else:
            message = AIMessage(content="entire context read")
        return ChatResult(generations=[ChatGeneration(message=message)])
