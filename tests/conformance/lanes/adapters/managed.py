"""`claude_managed` for the suite: the real harness over the fake Managed Agents API.

FIXTURES: `tests/fixtures/managed_lane.py` syncs the checked-in AI Engineer pack through the
real `ClaudeManagedPrepare` into `tests/fixtures/managed_agents.FakeManagedAgentsApi`
(`httpx.MockTransport`) and runs `ClaudeManagedHarness` over it inside a real Run. No
Anthropic API is called.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from mission_control.adapters.anthropic_managed.tools import ManagedTools
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.harness.hook_callbacks import InMemoryHookIntentLedger
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.application.execution.hosted_tools import HostedToolGate
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.application.frames.sink import InMemoryFrameStore
from tests.conformance.lanes.contract import LaneAdapter, LaneFake, Script
from tests.fixtures.cursor_controls import FAST, admitted_unit, compose_control_stack
from tests.fixtures.managed_agents import FakeManagedAgentsApi
from tests.fixtures.managed_lane import PROFILE, ManagedStack, managed_harness, managed_stack

# The fake's turn scripts for each claimed scenario's first turn (and the replacement turn).
_SCRIPTS: Final[Mapping[Script, tuple[str, ...]]] = {
    Script.FULL_TURN: ("full",),
    Script.HELD_TURN: ("held",),
    Script.INTERRUPTIBLE_TURN: ("held", "full"),
    Script.APPROVAL: ("approval",),
    Script.NO_USAGE: ("no_usage",),
}


class ClaudeManagedFake(LaneFake):
    @property
    def _stack(self) -> ManagedStack:
        stack: ManagedStack = self.control.local
        return stack

    @property
    def _api(self) -> FakeManagedAgentsApi:
        return self._stack.api

    def sends(self) -> list[tuple[str, str]]:
        return self._api.messages()

    async def until_held(self) -> None:
        await self._api.held.wait()

    def release(self) -> None:
        self._api.release()

    def cancels(self) -> int:
        return self._api.interrupts()

    def approval_answers(self) -> list[bool]:
        return [
            event["result"] == "allow"
            for _session, event in self._api.sent
            if event["type"] == "user.tool_confirmation"
        ]

    def ended(self) -> bool:
        """The session is archived and its deletion ordered after the retention interval."""

        return bool(self._api.archived()) and bool(self._stack.deletions.orders)


class ClaudeManagedConformance(LaneAdapter):
    profile = PROFILE

    def harness(self, tmp_path: Path) -> AgentHarness:
        return managed_stack(tmp_path).harness

    async def open(
        self,
        tmp_path: Path,
        script: Script,
        *,
        operation_changes: Mapping[str, Any] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> LaneFake:
        run_control, repository, run_id, unit, changes = await admitted_unit((), None)
        stack = managed_stack(
            tmp_path,
            scripts=_SCRIPTS[script],
            operation_changes={**changes, **dict(operation_changes or {})},
        )
        if broker is not None:

            async def signal(_identity, _call):
                return {"accepted": 1}

            tools = ManagedTools(
                client=stack.api.client(),
                gate=HostedToolGate(
                    fences=InMemoryStopFenceRepository(),
                    intents=InMemoryHookIntentLedger(),
                    broker=broker,
                    reviewers=("owner",),
                    allowed_tools=frozenset({"mc_prepare", "mc_signal", "bash"}),
                    wait_seconds=5.0,
                ),
                governed=None,
                signal=signal,
                steady_tools=stack.pack.agent_body([])["tools"],
            )
            stack.harness = managed_harness(
                stack.api,
                stack.pack,
                artifacts=stack.artifacts,
                deletions=stack.deletions,
                tools=tools,
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
            profile=PROFILE,
        )
        return ClaudeManagedFake(control)


__all__ = ["ClaudeManagedConformance"]
