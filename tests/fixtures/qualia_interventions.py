"""A real cancellable tool boundary used to observe ordinary live stage controls.

The tool supplies no research answer and no fabricated control receipt. The controller
must send real public commands while a model-requested call is awaiting release.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.adapters.deep_agents.materializer import tool_schema_digest
from mission_control.application.authoring.manifest_launch_inputs import CapabilityComponentBinding
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    CapabilityDefinition,
    CapabilityKind,
    DefinitionKind,
    ExactDefinitionRef,
)
from mission_control.domain.execution.contracts import DeepAgentToolComponent


class CheckpointInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Interventions:
    records: list[dict[str, Any]] = field(default_factory=list)
    gates: dict[str, asyncio.Event] = field(default_factory=dict)
    started: dict[str, Any] = field(default_factory=dict)
    released: set[str] = field(default_factory=set)
    entered: dict[str, asyncio.Event] = field(default_factory=dict)
    cancelled: dict[str, asyncio.Event] = field(default_factory=dict)
    # The stages whose live controls are authored (queued instruction, then interrupt/inject).
    positions: frozenset[str] = frozenset({"formulations", "studies"})

    async def checkpoint(self) -> str:
        live = CURRENT_INVOCATION.get()
        if live is None:
            raise ValueError("checkpoint requires the actual admitted invocation")
        position = live.position
        if position not in self.positions:
            return "No live-control checkpoint is authored for this stage. Continue the task."
        self.started[position] = live
        self.entered.setdefault(position, asyncio.Event()).set()
        self.records.append(
            {
                "event": "model_requested_checkpoint",
                "position": position,
                "run_id": live.run_id,
                "operation_id": live.operation_id,
                "attempt": live.operation_attempt,
                "generation": live.execution_generation,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        gate = self.gates.setdefault(position, asyncio.Event())
        try:
            async with asyncio.timeout(90):
                await gate.wait()
        except asyncio.CancelledError:
            self.cancelled.setdefault(position, asyncio.Event()).set()
            self.records.append(
                {
                    "event": "tool_cancelled",
                    "position": position,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            raise
        return (
            "The fixture control window is released. Read the actual new instruction/context "
            "messages in your conversation, then continue the source-grounded task."
        )

    def release(self, position: str) -> None:
        self.released.add(position)
        self.gates.setdefault(position, asyncio.Event()).set()

    def capability(self) -> tuple[Any, Any, Any, Any]:
        tool = StructuredTool.from_function(
            coroutine=self.checkpoint,
            name="fixture_checkpoint",
            args_schema=CheckpointInput,
            description="Pause at the real authored live-control test boundary before research.",
        )
        definition = CapabilityDefinition(
            kind=DefinitionKind.TOOL,
            capability_kind=CapabilityKind.TOOL,
            logical_id="tool.qualia.fixture_checkpoint",
            title="Live fixture checkpoint",
            description="Cancellable, read-only coordination boundary for live command proof.",
            maturity="experimental",
            attachment_targets=frozenset({"agent.main"}),
        )
        ref = ExactDefinitionRef(
            kind=DefinitionKind.TOOL,
            logical_id=definition.logical_id,
            revision=1,
            digest=sha256_digest(definition),
        )
        component = DeepAgentToolComponent(
            ref=ref,
            tool_name=tool.name,
            schema_digest=tool_schema_digest(tool),
            attachment_target="agent.main",
        )
        binding = CapabilityComponentBinding(kind="tool", catalog_digest=ref.digest, tool=component)
        return definition, component, binding, tool
