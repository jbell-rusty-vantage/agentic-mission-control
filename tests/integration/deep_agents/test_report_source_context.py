"""Real Deep Agents backend delivery/read of both canonical fixture contexts; no paid model.

This proves file receipt and scripted agent reading, not KS persistence or semantic judgment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tests.integration.deep_agents.test_wi02_transfer_plan_lane import (
    PlanReadingModel,
    _invocation,
    _materializer,
    _selection,
    activity_attempt,
    registry,
)
from tests.unit.test_report_source_context import context

from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
from mission_control.adapters.deep_agents.materializer import ExactDeepAgentMaterializer
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.domain.context.transfer import InputSource, TransferInput


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


@pytest.mark.asyncio
@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
async def test_real_agent_reads_all_verified_context_bytes(tmp_path: Path, application: str):
    out = tmp_path / application
    manifest = context.materialize_context(
        context.MC_ROOT.parents[1], context.PROFILES / f"{application}.json", out
    )
    context.verify_context(out, manifest["manifest_digest"])
    expected = (out / "context.txt").read_bytes()
    invocation, binding, bundle = _invocation()
    selection = _selection().model_copy(
        update={
            "inputs": (
                TransferInput(
                    name="foundation",
                    source=InputSource.literal("text/plain@1", expected.decode()),
                    purpose="dependent_input",
                    placement="file",
                ),
            )
        }
    )
    invocation = invocation.model_copy(
        update={"binding": invocation.binding.model_copy(update={"transfer": selection})}
    )
    materializer, store = _materializer()
    FullContextReader.expected = expected
    FullContextReader.observed = {}
    FullContextReader.file_path = (
        f"/inputs/foundation/{context.digest(expected)[7:23]}/foundation.txt"
    )
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, FullContextReader())),
        transfer=materializer,
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(invocation.binding, activity_attempt(1), dispatching=True)
    result = await adapter.execute(invocation.model_copy(update={"checkpoint_plan": plan}), {})
    assert result.output_text == "entire context read"
    assert sorted(FullContextReader.observed) == list(
        range(1, len(expected.decode().splitlines()) + 1)
    )
    observed = (
        "\n".join(FullContextReader.observed[i] for i in sorted(FullContextReader.observed)) + "\n"
    )
    assert observed.encode() == expected
    (sealed,) = store.plans.values()
    (receipt,) = await store.receipts(sealed.receiver.scope, sealed.plan_id)
    assert receipt.result == "ready"
    assert receipt.realized_backend == "deep_agents:state"
    assert {item.probe for item in receipt.delivered} == {"state_files_read"}
