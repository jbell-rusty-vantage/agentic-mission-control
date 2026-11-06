"""The lane conformance contract (SPEC-06 section 3): scenarios, claims, fakes and adapters.

Every lane profile runs the same scenarios against its fake provider. Which scenarios a lane
must pass is read from its declared describe, never chosen by the lane: a scenario is
*claimed* when every describe cell it exercises is `native` or `emulated` (and every delivery
command it needs is not `unsupported`). A claimed scenario either passes or carries a
`DeclaredException` that names where the behaviour is proven instead; an unclaimed scenario is
not run, and describe honesty proves the lane refuses it.

A lane registers by subclassing `LaneAdapter` (its fake provider behind `LaneFake`) and adding
one entry to `registry.CONFORMANCE_LANES`; see README.md beside this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Final

from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.protocol import AgentHarness, SessionLane
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import LaneDescribe, LaneProfileName, SnapshotManifest
from tests.fixtures.cursor_controls import ControlStack


class Scenario(StrEnum):
    """The SPEC-06 section 3 scenarios, in the order the specification lists them."""

    DESCRIBE_HONESTY = "describe_honesty"
    START_OBSERVE_SETTLE = "start_observe_settle"
    REATTACH_MID_STREAM = "reattach_mid_stream"
    SEND_TURN_WHILE_BUSY = "send_turn_while_busy"
    CANCEL = "cancel"
    INTERRUPT_AND_INJECT = "interrupt_and_inject"
    APPROVAL_ROUND_TRIP = "approval_round_trip"
    BUDGET_STOP = "budget_stop"
    FORK_EMULATION = "fork_emulation"
    CONTINUATION_HANDOVER = "continuation_handover"
    UNKNOWN_USAGE = "unknown_usage"


_IMPLEMENTED: Final = frozenset({"native", "emulated"})


@dataclass(frozen=True)
class Claim:
    """The describe cells a scenario exercises: when all hold, the lane claims the scenario."""

    controls: tuple[str, ...] = ()
    delivery: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    approval_modes: tuple[str, ...] = ()

    def holds(self, describe: LaneDescribe) -> bool:
        return (
            all(describe.controls[name] in _IMPLEMENTED for name in self.controls)
            and all(describe.delivery_semantics[name] != "unsupported" for name in self.delivery)
            and all(describe.feature(name).status in _IMPLEMENTED for name in self.features)
            and all(mode in describe.approval_modes for mode in self.approval_modes)
        )


# Describe honesty is every lane's duty; every other scenario is claimed by these cells.
CLAIMS: Final[Mapping[Scenario, Claim]] = MappingProxyType(
    {
        Scenario.DESCRIBE_HONESTY: Claim(),
        Scenario.START_OBSERVE_SETTLE: Claim(
            controls=("prepare", "start", "send_turn", "observe", "usage", "end_session")
        ),
        Scenario.REATTACH_MID_STREAM: Claim(controls=("observe", "reattach")),
        Scenario.SEND_TURN_WHILE_BUSY: Claim(
            controls=("send_turn",), delivery=("queue_instruction",)
        ),
        Scenario.CANCEL: Claim(controls=("cancel_turn",), delivery=("cancel",)),
        Scenario.INTERRUPT_AND_INJECT: Claim(
            controls=("send_turn",), delivery=("interrupt_and_inject",)
        ),
        Scenario.APPROVAL_ROUND_TRIP: Claim(
            features=("approval_suspension",), approval_modes=("provider_permission",)
        ),
        Scenario.BUDGET_STOP: Claim(controls=("usage",)),
        Scenario.FORK_EMULATION: Claim(controls=("snapshot", "fork"), delivery=("fork",)),
        Scenario.CONTINUATION_HANDOVER: Claim(
            delivery=("request_continuation",), features=("continuation",)
        ),
        Scenario.UNKNOWN_USAGE: Claim(controls=("usage",)),
    }
)


def claims(describe: LaneDescribe, scenario: Scenario) -> bool:
    return CLAIMS[scenario].holds(describe)


@dataclass(frozen=True)
class DeclaredException:
    """A claimed scenario this suite does not run for a lane, and where it is proven instead.

    `evidence` names repository paths (tests or qualification records) that exist; the
    registry test refuses an exception without evidence, for describe honesty, or for a
    scenario the lane does not claim.
    """

    reason: str
    evidence: tuple[str, ...]


class Script(StrEnum):
    """What the fake provider does on the first turn (every adapter scripts each one)."""

    # The turn runs to a `finished` result and reports its token usage.
    FULL_TURN = "full_turn"
    # The turn holds at a running tool until released (or cancelled), then finishes.
    HELD_TURN = "held_turn"
    # HELD_TURN, and the provider honours an interrupt and runs a replacement turn.
    INTERRUPTIBLE_TURN = "interruptible_turn"
    # HELD_TURN, and a fresh session (a continuation target) can run the next turn.
    CONTINUATION = "continuation"
    # FULL_TURN, but the provider reports neither tokens nor cost for the turn.
    NO_USAGE = "no_usage"
    # The turn asks for a provider permission (one tool call) before it finishes.
    APPROVAL = "approval"


class LaneFake(ABC):
    """One lane's fake provider inside a real Run: what every scenario drives and inspects.

    `control` composes the lane's harness with the production lane turn service, the Run's
    command mailbox and the interrupt_and_inject service; the abstract methods read the fake
    provider (what it was sent and asked), so scenarios assert provider-side effects without
    knowing the lane.
    """

    def __init__(self, control: ControlStack) -> None:
        self.control = control

    @property
    def profile(self) -> str:
        return self.control.profile

    @property
    def operation(self) -> OperationExecutionRequest:
        return self.control.operation

    @property
    def identity(self) -> LaneExecutionIdentity:
        return self.control.identity

    @property
    def harness(self) -> SessionLane:
        harness: SessionLane = self.control.local.harness
        return harness

    @property
    def describe(self) -> LaneDescribe:
        return self.harness.describe()

    def frames(self) -> list[Any]:
        """The execution's persisted provider frames, in arrival order."""

        executions = self.control.lanes.frames._executions
        execution = executions.get(self.identity.harness_execution_id)
        if execution is None:
            return []
        return sorted(execution.frames.values(), key=lambda frame: frame.arrival_ordinal)

    @abstractmethod
    def sends(self) -> list[tuple[str, str]]:
        """`(native session ref, text)` of every turn the provider received, in order."""

    @abstractmethod
    async def until_held(self) -> None:
        """Return once the provider holds the first turn (HELD_TURN and its variants)."""

    @abstractmethod
    def release(self) -> None:
        """Let the held turn continue to its result."""

    @abstractmethod
    def cancels(self) -> int:
        """How many cancel or interrupt requests reached the provider."""

    @abstractmethod
    def ended(self) -> bool:
        """Whether `end_session` released the session's native resources (lease, agent)."""

    def approval_answers(self) -> list[bool]:
        """The provider-side answer (allowed or not) to each permission it asked for."""

        raise NotImplementedError(f"{self.profile} scripts no provider permission")


@dataclass(frozen=True)
class ContinuationPorts:
    """The lane's continuation registration parts: sealed from the live session's workspace,
    hydrated into a fresh native session (ADR-0039). `staging` is the artifact port both share
    with the continuation service (`None`: the service stages into its own)."""

    snapshots: Any
    hydrator: Any
    staging: Any = None


@dataclass(frozen=True)
class ForkedSession:
    """The first session of a run forked from a snapshot, and what its workspace restored."""

    native_session_ref: str
    restored: bytes | None


class LaneAdapter(ABC):
    """How the suite builds one lane profile. Override exactly what the describe claims."""

    profile: LaneProfileName
    exceptions: ClassVar[Mapping[Scenario, DeclaredException]] = MappingProxyType({})

    @abstractmethod
    def harness(self, tmp_path: Path) -> AgentHarness:
        """The lane's harness as a worker registers it (the describe-honesty subject)."""

    async def open(
        self,
        tmp_path: Path,
        script: Script,
        *,
        operation_changes: Mapping[str, Any] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> LaneFake:
        """The lane's fake provider playing `script` inside a fresh admitted Run (`broker`
        binds provider permissions for APPROVAL)."""

        raise NotImplementedError(f"{self.profile} has no conformance fake")

    def continuation_ports(self, fake: LaneFake) -> ContinuationPorts:
        raise NotImplementedError(f"{self.profile} registers no continuation hydrator")

    async def write_workspace(self, fake: LaneFake, path: str, content: bytes) -> None:
        """Change the live session's workspace while its turn runs, as the agent would."""

        raise NotImplementedError(f"{self.profile} emulates no fork")

    async def fork(
        self, fake: LaneFake, snapshot: SnapshotManifest, tmp_path: Path, path: str
    ) -> ForkedSession:
        """Start the first session of a run forked from `snapshot` (the derived run's packet
        names it) and read `path` from the derived workspace (`None` when absent)."""

        raise NotImplementedError(f"{self.profile} emulates no fork")


# The adapter hooks each claimed scenario calls.
_SESSION: Final = ("open",)
SCENARIO_HOOKS: Final[Mapping[Scenario, tuple[str, ...]]] = MappingProxyType(
    {
        Scenario.DESCRIBE_HONESTY: ("harness",),
        Scenario.START_OBSERVE_SETTLE: _SESSION,
        Scenario.REATTACH_MID_STREAM: _SESSION,
        Scenario.SEND_TURN_WHILE_BUSY: _SESSION,
        Scenario.CANCEL: _SESSION,
        Scenario.INTERRUPT_AND_INJECT: _SESSION,
        Scenario.APPROVAL_ROUND_TRIP: _SESSION,
        Scenario.BUDGET_STOP: _SESSION,
        Scenario.FORK_EMULATION: ("open", "write_workspace", "fork"),
        Scenario.CONTINUATION_HANDOVER: ("open", "continuation_ports"),
        Scenario.UNKNOWN_USAGE: _SESSION,
    }
)


def overrides(adapter: LaneAdapter, hook: str) -> bool:
    """True when the adapter implements `hook` instead of inheriting the refusing default."""

    return getattr(type(adapter), hook) is not getattr(LaneAdapter, hook)


__all__ = [
    "CLAIMS",
    "SCENARIO_HOOKS",
    "Claim",
    "ContinuationPorts",
    "DeclaredException",
    "ForkedSession",
    "LaneAdapter",
    "LaneFake",
    "Scenario",
    "Script",
    "claims",
    "overrides",
]
