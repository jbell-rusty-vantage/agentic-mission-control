"""`claude_agent_sdk` for the suite: the real harness over the scripted SDK client.

FIXTURES: `tests/unit/claude/fixtures.py` replays wire-shaped records through the pinned SDK's
own parser; provider permissions bind through the production `BrokerPermissionBinding`. No
Claude Code runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mission_control.adapters.claude.approvals import BrokerPermissionBinding
from mission_control.adapters.claude.continuation import (
    ClaudeSessionHydrator,
    ClaudeWorkspaceSnapshots,
)
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.domain.execution.contracts import OperationExecutionRequest
from tests.conformance.lanes.contract import (
    ContinuationPorts,
    DeclaredException,
    LaneAdapter,
    LaneFake,
    Scenario,
    Script,
)
from tests.conformance.lanes.drive import REVIEWER
from tests.fixtures.continuation import FakeStaging
from tests.fixtures.cursor_controls import FAST, admitted_unit, compose_control_stack
from tests.unit.claude.fixtures import (
    PROFILE,
    FixtureScript,
    ScriptRecord,
    claude_operation,
    claude_stack,
)

_SCRIPTS: Mapping[Script, str] = {
    Script.FULL_TURN: "full_run",
    Script.HELD_TURN: "interrupted_then_replaced",
    Script.INTERRUPTIBLE_TURN: "interrupted_then_replaced",
    Script.CONTINUATION: "continuation_source",
    Script.NO_USAGE: "full_run",
    Script.APPROVAL: "subagent_task",
}
# What a `result` (and an assistant message) reports about the turn's usage and cost.
_USAGE_KEYS = frozenset({"usage", "modelUsage", "total_cost_usd"})


class ClaudeFake(LaneFake):
    @property
    def _clients(self) -> list[Any]:
        clients: list[Any] = self.control.local.factory.clients
        return clients

    def sends(self) -> list[tuple[str, str]]:
        return [
            (client.script.session_id, text)
            for client in self._clients
            for _uuid, text in client.sent
        ]

    async def until_held(self) -> None:
        source = await self.control.local.factory.connected()
        await source.held.wait()

    def release(self) -> None:
        self._clients[0].release.set()

    def cancels(self) -> int:
        return sum(client.interrupts for client in self._clients)

    def ended(self) -> bool:
        return bool(self.control.local.workspace.released)

    def approval_answers(self) -> list[bool]:
        return [allowed for client in self._clients for _tool, allowed in client.permission_calls]


def _without_usage(record: ScriptRecord) -> ScriptRecord:
    if record.message is None:
        return record
    message = {key: value for key, value in record.message.items() if key not in _USAGE_KEYS}
    inner = message.get("message")
    if isinstance(inner, dict):
        message["message"] = {key: value for key, value in inner.items() if key not in _USAGE_KEYS}
    return replace(record, message=message)


class ClaudeAgentSdkConformance(LaneAdapter):
    profile = "claude_agent_sdk"
    # Cross-provider control (2026-11-05): `fork` is emulated by the lane's time travel (the
    # state-root transcript mirror truncated at the point, resumed under a new session id),
    # a conversation fork seeded through `LaneSeedHead`, not the workspace-snapshot fork this
    # scenario drives (the derived workspace is not restored by the seed); proven in the lane suite.
    exceptions = MappingProxyType(
        {
            Scenario.FORK_EMULATION: DeclaredException(
                reason=(
                    "fork is a conversation fork seeded from a cognition point "
                    "(time_travel.seed_fork), not a workspace-snapshot restore"
                ),
                evidence=(
                    "tests/unit/claude/test_time_travel.py",
                    "tests/unit/claude/test_cognition_points.py",
                ),
            )
        }
    )

    def harness(self, tmp_path: Path) -> AgentHarness:
        return claude_stack(tmp_path).harness

    async def open(
        self,
        tmp_path: Path,
        script: Script,
        *,
        operation_changes: Mapping[str, Any] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> LaneFake:
        run_control, repository, run_id, unit, changes = await admitted_unit((), None)
        operation = OperationExecutionRequest.model_validate(
            {
                **claude_operation().model_dump(mode="python"),
                **changes,
                **dict(operation_changes or {}),
            }
        )
        permissions = (
            BrokerPermissionBinding(broker, wait_seconds=5.0, reviewers=(REVIEWER,))
            if broker is not None
            else None
        )
        stack = claude_stack(
            tmp_path, _SCRIPTS[script], operation=operation, permissions=permissions
        )
        if script is Script.NO_USAGE:
            loaded = stack.factory.script
            stack.factory.script = replace(
                loaded, records=[_without_usage(record) for record in loaded.records]
            )
        if script is Script.CONTINUATION:
            stack.factory.fresh_scripts.append(FixtureScript.load("continuation_target"))
        control = compose_control_stack(
            stack,
            stack.harness,
            stack.frames,
            operation,
            run_control=run_control,
            repository=repository,
            run_id=run_id,
            unit=unit,
            settings=FAST,
            profile=PROFILE,
        )
        return ClaudeFake(control)

    def continuation_ports(self, fake: LaneFake) -> ContinuationPorts:
        harness = fake.control.local.harness
        staging = FakeStaging()
        return ContinuationPorts(
            snapshots=ClaudeWorkspaceSnapshots(harness, staging),
            hydrator=ClaudeSessionHydrator(harness, staging),
            staging=staging,
        )


__all__ = ["ClaudeAgentSdkConformance"]
