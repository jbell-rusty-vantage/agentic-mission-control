"""`deep_agents`: the governed lane, held to describe honesty here.

The operation boundary runs Deep Agents through its bounded `operation.execute` path
(`LaneTurnService.governed`); `lane.turn` never drives it, so the session scenarios, which run
through the lane turn service, are declared exceptions that cite the suites proving the same
behaviour on the governed path.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.operations.conformance import ConformanceRuntime
from mission_control.application.execution.harness.protocol import AgentHarness
from tests.conformance.lanes.contract import DeclaredException, LaneAdapter, Scenario

_GOVERNED = (
    "deep_agents is a governed lane: the operation boundary runs it through the bounded "
    "operation.execute path and lane.turn never drives it (LaneTurnService.governed)"
)
_PROTOCOL = "tests/unit/harness/test_lane_registry.py"


def _governed(*evidence: str) -> DeclaredException:
    return DeclaredException(reason=_GOVERNED, evidence=evidence)


class DeepAgentsConformance(LaneAdapter):
    profile = "deep_agents"
    exceptions = MappingProxyType(
        {
            Scenario.START_OBSERVE_SETTLE: _governed(
                _PROTOCOL, "tests/acceptance/control_plane/test_wp_cp_040.py"
            ),
            Scenario.REATTACH_MID_STREAM: _governed(
                _PROTOCOL, "tests/unit/operations/test_rrm_009_cancellation_composition.py"
            ),
            Scenario.SEND_TURN_WHILE_BUSY: _governed(
                _PROTOCOL, "tests/unit/run_control/test_ft_f1_command_mailbox.py"
            ),
            Scenario.CANCEL: _governed(
                _PROTOCOL, "tests/unit/operations/test_rrm_008_cancellation.py"
            ),
            Scenario.INTERRUPT_AND_INJECT: _governed(
                "tests/unit/operations/test_ft_f2_interrupt_and_inject.py"
            ),
            Scenario.BUDGET_STOP: _governed("tests/unit/operations/test_operation_execution.py"),
            Scenario.FORK_EMULATION: _governed(
                "tests/unit/run_control/test_ft_f4_fork_instruction.py",
                "tests/unit/operations/test_fork_reuse_execution.py",
            ),
            Scenario.UNKNOWN_USAGE: _governed(_PROTOCOL),
        }
    )

    def harness(self, tmp_path: Path) -> AgentHarness:
        return DeepAgentsHarness(ConformanceRuntime())


__all__ = ["DeepAgentsConformance"]
