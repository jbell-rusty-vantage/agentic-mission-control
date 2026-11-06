"""Codex Agents conformance through the real harness and a stateful HTTP fake."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.application.frames.sink import InMemoryFrameStore
from tests.conformance.lanes.contract import LaneAdapter, LaneFake, Script
from tests.fixtures.agents_lane import AgentsStack, agents_stack
from tests.fixtures.cursor_controls import FAST, admitted_unit, compose_control_stack

_SCRIPTS = {
    Script.FULL_TURN: ("full",),
    Script.HELD_TURN: ("held",),
    Script.INTERRUPTIBLE_TURN: ("held", "full"),
    Script.NO_USAGE: ("no_usage",),
}


class AgentsFake(LaneFake):
    @property
    def stack(self) -> AgentsStack:
        return self.control.local

    def sends(self) -> list[tuple[str, str]]:
        return self.stack.api.sends

    async def until_held(self) -> None:
        await self.stack.api.held.wait()

    def release(self) -> None:
        self.stack.api.release()

    def cancels(self) -> int:
        return self.stack.api.cancel_count

    def ended(self) -> bool:
        return bool(self.stack.deletions.orders)


class CodexAgentsConformance(LaneAdapter):
    profile = "codex_agents"

    def harness(self, tmp_path: Path) -> AgentHarness:
        return agents_stack(tmp_path).harness

    async def open(
        self,
        tmp_path: Path,
        script: Script,
        *,
        operation_changes: Mapping[str, Any] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> LaneFake:
        del broker
        run_control, repository, run_id, unit, changes = await admitted_unit((), None)
        stack = agents_stack(
            tmp_path, _SCRIPTS[script], **{**changes, **dict(operation_changes or {})}
        )
        control = compose_control_stack(
            stack,
            stack.harness,
            InMemoryFrameStore(),
            stack.operation,
            run_control=run_control,
            repository=repository,
            run_id=run_id,
            unit=unit,
            settings=FAST,
            profile=self.profile,
        )
        return AgentsFake(control)
