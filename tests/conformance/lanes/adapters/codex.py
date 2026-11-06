"""`codex` for the suite: the real harness over the FIXTURE app-server.

FIXTURES: `tests/unit/codex/fixture_app_server.py` speaks the pinned app-server v2 protocol
from scripted turns (each `turn/start` plays the next script; a later launch, a continuation
target, plays its own). No Codex runs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mission_control.adapters.codex.continuation import (
    CodexSessionHydrator,
    CodexWorkspaceSnapshots,
)
from mission_control.adapters.codex.harness import CodexLocalHarness
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.application.frames.sink import InMemoryFrameStore
from tests.conformance.lanes.contract import (
    ContinuationPorts,
    DeclaredException,
    LaneAdapter,
    LaneFake,
    Scenario,
    Script,
)
from tests.fixtures.continuation import FakeStaging
from tests.fixtures.cursor_controls import FAST, admitted_unit, compose_control_stack
from tests.unit.codex.fixture_app_server import FixtureLauncher, load_script
from tests.unit.codex.support import PROFILE, TmpLeaser, build_harness, codex_operation

# The scripted turns of the first app-server, in `turn/start` order.
_TURNS: Mapping[Script, tuple[str, ...]] = {
    Script.FULL_TURN: ("turn_full",),
    Script.HELD_TURN: ("turn_hold",),
    Script.INTERRUPTIBLE_TURN: ("turn_hold", "turn_full"),
    Script.CONTINUATION: ("turn_hold",),
    Script.NO_USAGE: ("turn_full",),
    Script.APPROVAL: ("turn_with_approval",),
}
_ACCEPTED = {"result": {"decision": "accept"}}


@dataclass(frozen=True)
class CodexParts:
    """The harness and the FIXTURE app-server launcher and leaser behind it."""

    harness: CodexLocalHarness
    launcher: FixtureLauncher
    leaser: TmpLeaser


class CodexFake(LaneFake):
    @property
    def _servers(self) -> list[Any]:
        return [launch.server for launch in self.control.local.launcher.launches]

    def sends(self) -> list[tuple[str, str]]:
        return [
            (
                str(params["threadId"]),
                "".join(str(item.get("text", "")) for item in params.get("input", [])),
            )
            for server in self._servers
            for method, params in server.records
            if method == "turn/start"
        ]

    async def until_held(self) -> None:
        launcher = self.control.local.launcher
        await launcher.launched.wait()
        await launcher.launches[0].server.held.wait()

    def release(self) -> None:
        self._servers[0].release.set()

    def cancels(self) -> int:
        return sum(len(server.interrupts) for server in self._servers)

    def ended(self) -> bool:
        leases = self.control.local.leaser.leases.values()
        return bool(leases) and all(lease.released for lease in leases)

    def approval_answers(self) -> list[bool]:
        return [answer == _ACCEPTED for server in self._servers for _m, answer in server.approvals]


def _turn_scripts(names: Sequence[str], *, usage: bool) -> list[Sequence[dict[str, Any]]]:
    scripts: list[Sequence[dict[str, Any]]] = []
    for name in names:
        steps = [step for step in load_script(name) if usage or step.get("step") != "usage"]
        if name == "turn_hold" and usage:
            # This positive fake reports consumption before interruption. Move the
            # existing scripted counter once; never manufacture a cancellation total.
            counters = [step for step in steps if step.get("step") == "usage"]
            assert len(counters) == 1
            steps = [step for step in steps if step.get("step") != "usage"]
            hold = next(index for index, step in enumerate(steps) if step.get("step") == "hold")
            steps[hold:hold] = counters
        scripts.append(steps)
    return scripts


class CodexConformance(LaneAdapter):
    profile = "codex"
    # Cross-provider control (2026-11-05): `fork` is emulated by the lane's time travel
    # (`thread/fork` through a turn, a reconstructed transcript inside one), a conversation
    # fork seeded through `LaneSeedHead`, not the workspace-snapshot fork this scenario
    # drives (the derived workspace is not restored by the seed); proven in the lane suite.
    exceptions = MappingProxyType(
        {
            Scenario.FORK_EMULATION: DeclaredException(
                reason=(
                    "fork is a conversation fork seeded from a cognition point "
                    "(time_travel.seed_fork), not a workspace-snapshot restore"
                ),
                evidence=(
                    "tests/unit/codex/test_time_travel.py",
                    "tests/unit/codex/test_cognition_points.py",
                ),
            )
        }
    )

    def __init__(self, *, held_usage: bool = True) -> None:
        self._held_usage = held_usage

    def harness(self, tmp_path: Path) -> AgentHarness:
        harness, *_parts = build_harness(tmp_path, FixtureLauncher())
        return harness

    async def open(
        self,
        tmp_path: Path,
        script: Script,
        *,
        operation_changes: Mapping[str, Any] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> LaneFake:
        run_control, repository, run_id, unit, changes = await admitted_unit((), None)
        operation = codex_operation(**changes, **dict(operation_changes or {}))
        launcher = FixtureLauncher(
            scripts=_turn_scripts(
                _TURNS[script],
                usage=script is not Script.NO_USAGE
                and (self._held_usage or script is not Script.HELD_TURN),
            ),
            launch_scripts=(
                {1: _turn_scripts(("turn_full",), usage=True)}
                if script is Script.CONTINUATION
                else {}
            ),
        )
        harness, leaser, _artifacts, _auth = build_harness(tmp_path, launcher, broker=broker)
        control = compose_control_stack(
            CodexParts(harness, launcher, leaser),
            harness,
            InMemoryFrameStore(),
            operation,
            run_control=run_control,
            repository=repository,
            run_id=run_id,
            unit=unit,
            settings=FAST,
            profile=PROFILE,
        )
        return CodexFake(control)

    def continuation_ports(self, fake: LaneFake) -> ContinuationPorts:
        harness = fake.control.local.harness
        staging = FakeStaging()
        return ContinuationPorts(
            snapshots=CodexWorkspaceSnapshots(harness, staging),
            hydrator=CodexSessionHydrator(harness, staging),
            staging=staging,
        )


__all__ = ["CodexConformance"]
