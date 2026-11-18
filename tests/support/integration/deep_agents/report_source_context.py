"""The scripted full-context reader (the LLM boundary) of the Deep Agents delivery tests.

`FULL_CONTEXT_READER` reads one delivered file whole in 150-line pages; the WI-02 lane test and
the report-source real-service and replay tests configure it and read back what it saw.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from tests.support.models import ScriptedChatModel


@dataclass
class FullContextReader:
    """Reads `file_path` in 150-line pages, then records the lines it saw (`observed`)."""

    expected: bytes = b""
    file_path: str = ""
    observed: dict[int, str] = field(default_factory=dict)

    def __call__(self, messages: list[BaseMessage], call: int) -> AIMessage:
        del call
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
            return AIMessage(
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
        return AIMessage(content="entire context read")

    def model(self) -> ScriptedChatModel:
        return ScriptedChatModel(script=self, label="wi02-plan-reader", usage=None)


# The one full-context reader the report-source tests configure and read back.
FULL_CONTEXT_READER = FullContextReader()
