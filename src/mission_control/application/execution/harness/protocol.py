"""The provider-neutral AgentHarness protocol (SPEC-07 section 1, ADR-0018; FT-G1).

Every lane implements `describe` plus nine operations. A lane that declares an operation
`unsupported` (or `unqualified`) in its describe raises `HarnessUnsupported` for it; any other
error from such an operation is a conformance failure. `observe` is resumable by an opaque,
lane-specific cursor (LangGraph checkpoint id, bridge offset, SSE event id).

`OperationLane` is what `OperationExecutionService` needs from a registered lane today: the
bounded `execute` path of the `RuntimePort` family (the Deep Agents lane keeps it until the
`lane.turn` activities of FT-G2 drive every lane through the protocol).

`WorkspaceLeasingLane` is a local lane whose workspaces the MP-04 allocator leases on the
worker: `lane.cleanup` asks it to remove a settled unit's released lease (MO-05).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from typing import Literal, Protocol, runtime_checkable

from mission_control.application.execution.harness.native_run_usage import NativeRun
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    RuntimeInvocation,
    RuntimeResult,
)
from mission_control.domain.execution.history_reconciliation import HistoryReplayComplete
from mission_control.domain.execution.lane_turns import CleanupOutcome, ClosingFacts
from mission_control.domain.execution.lanes import (
    CancelReceipt,
    CancelTurnRequest,
    CleanupReceipt,
    EndSessionRequest,
    LaneDescribe,
    LaneFrame,
    ObserveRequest,
    PreparedSession,
    PrepareRequest,
    ProviderStatus,
    ReattachRequest,
    SendTurnRequest,
    SessionHandle,
    SnapshotManifest,
    SnapshotRequest,
    StartRequest,
    StatusRequest,
    TurnHandle,
    UsageReport,
    UsageRequest,
)
from mission_control.domain.frames.contracts import ProviderFrame


class HarnessUnsupported(NotImplementedError):
    """The lane profile does not (or not yet, qualified) support this operation."""

    def __init__(self, operation: str, lane_profile: str, reason: str) -> None:
        super().__init__(f"{operation} is {reason} on lane profile {lane_profile}")
        self.operation = operation
        self.lane_profile = lane_profile
        self.reason = reason


class NativeTurnLost(LookupError):
    """The provider no longer knows the native turn (a local bridge or its store is gone).

    `lane.turn` never re-sends a lost turn: the unit becomes `in_doubt` and reconciliation
    decides (SPEC-07 section 4.1 step 2)."""


@runtime_checkable
class AgentHarness(Protocol):
    def describe(self) -> LaneDescribe: ...

    async def prepare(self, request: PrepareRequest) -> PreparedSession: ...

    async def start(self, request: StartRequest) -> SessionHandle: ...

    async def reattach(self, request: ReattachRequest) -> SessionHandle: ...

    async def send_turn(self, request: SendTurnRequest) -> TurnHandle: ...

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt: ...

    def observe(self, request: ObserveRequest) -> AsyncIterator[LaneFrame]: ...

    async def snapshot(self, request: SnapshotRequest) -> SnapshotManifest: ...

    async def usage(self, request: UsageRequest) -> UsageReport: ...

    async def end_session(self, request: EndSessionRequest) -> CleanupReceipt: ...


@runtime_checkable
class SessionLane(AgentHarness, Protocol):
    """A lane `lane.turn` drives through the protocol itself, segment by segment (FT-G2).

    Beside the ten operations it reads its provider's terminal frame into `ClosingFacts`,
    reconciles a session by native identity (`lane.status`), and turns a persisted frame's
    provider key back into its resumable cursor, so a resumed segment observes from the
    persisted frames (the truth) rather than from a throttled heartbeat (a hint).
    """

    def stage(self, harness_execution_id: str, operation: OperationExecutionRequest) -> None:
        """Hand the lane the bound operation (binding, packet slots, prompt) of an execution
        before any operation on it; idempotent for the same operation."""
        ...

    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts: ...

    async def status(self, request: StatusRequest) -> ProviderStatus: ...

    def resume_cursor(self, provider_key: str) -> str | None: ...


@runtime_checkable
class ValidatesOperationRequest(Protocol):
    """A lane that checks its own sealed binding against an operation's authority envelope.

    `OperationExecutionService` asks with `isinstance` and calls it before it verifies the run's
    authority and budget reservation and before it binds or claims the attempt, so bytes that
    name another run, operation, attempt, configuration, control revision, workspace, grant,
    reservation or unit are refused at admission (OC-R2). Raises `ValueError` to refuse.
    """

    def validate_request(self, operation: OperationExecutionRequest) -> None: ...


@runtime_checkable
class HistoryReconciliationLane(Protocol):
    """Finite native history on the existing owner, with no create/send/cancel operation."""

    def reconcile_history(
        self, request: ObserveRequest
    ) -> AsyncIterator[LaneFrame | HistoryReplayComplete]: ...


@runtime_checkable
class WorkspaceLeasingLane(Protocol):
    """A lane whose workspaces Mission Control leases on the worker (MO-05, SPEC-03 section
    2): the operation workflow cleans a holder generation's released lease after Artifact
    registration and settlement. Idempotent; a refusal (`WorkspaceError`) keeps the worktree.
    """

    async def cleanup_workspace(
        self, *, request_scope: str, harness_execution_id: str, generation: int
    ) -> CleanupOutcome: ...


@runtime_checkable
class NativeRunUsageLane(Protocol):
    """A lane whose closing usage is attributed per native run from the attempt's provider
    frames, not from the closing turn's own usage read alone (OC-R3: the Cursor and Codex
    lanes; the lane session driver asks `isinstance` instead of naming them).

    The driver reads the semantic attempt's frames, asks the lane for one usage report per
    native run, merges the closing facts and each run's exact usage read by the lane's rules
    and summarizes the result (`native_run_usage.summarize_usage`). Every method is pure.
    """

    def observed_usage(self, frames: Iterable[ProviderFrame]) -> dict[NativeRun, UsageReport]:
        """One attributable usage report per native session/run the frames name."""
        ...

    def cancelled_turn_usage(
        self, frames: Iterable[ProviderFrame], turn_ref: str | None
    ) -> UsageReport:
        """The attributed usage of a cancelled turn (`turn_ref`; `None`: every run)."""
        ...

    def attribute_closing_usage(
        self, reports: dict[NativeRun, UsageReport], current: NativeRun, closing: UsageReport
    ) -> None:
        """Merge the closing facts' usage of the current native run into `reports`."""
        ...

    def attests_native_run(self, run: NativeRun) -> bool:
        """Whether the lane's own usage read can attest this native run (a provider child
        run it cannot attest keeps its observed report)."""
        ...

    def reconcile_reported_usage(self, observed: UsageReport, reported: UsageReport) -> UsageReport:
        """The report a native run keeps after the lane's exact usage read of it."""
        ...

    def unknown_usage_reconciliation_reason(self) -> str | None:
        """The loss reason when a natively completed session's usage stays unknown and its
        claim must be retained for reconciliation; `None`: settle it as unknown."""
        ...


@runtime_checkable
class CancelledCloseLane(Protocol):
    """A lane whose provider reports a cancelled turn's own close (with its usage), which a
    command cancel observes before it settles (OC-R3: Managed Agents, the Agents API and
    Codex; the lane session driver asks `isinstance` instead of naming them).

    `cancelled_close` is `"observe"` when the close is read from the provider after the
    interrupt, `"observe_or_stored"` when the driver may first reuse this owner's exact durable
    close from the attempt's stored frames (a cancelled observation may have persisted it
    without flushing its segment cursor).
    """

    @property
    def cancelled_close(self) -> Literal["observe", "observe_or_stored"]: ...


class OperationLane(AgentHarness, Protocol):
    """A lane `OperationExecutionService` dispatches a bound operation attempt to."""

    def requires_checkpoint_lineage(self, request: OperationExecutionRequest) -> bool:
        """Whether executing `request` on this lane needs checkpoint lineage composition."""
        ...

    async def execute(
        self, invocation: RuntimeInvocation, resolved_secrets: Mapping[str, str]
    ) -> RuntimeResult: ...


HARNESS_PROTOCOL_METHODS = (
    "describe",
    "prepare",
    "start",
    "reattach",
    "send_turn",
    "cancel_turn",
    "observe",
    "snapshot",
    "usage",
    "end_session",
)


class UnsupportedHarnessOperations:
    """Mixin: every protocol operation raises `HarnessUnsupported` with its declared reason.

    A lane overrides exactly the operations its describe reports `native` or `emulated`; the
    conformance test checks that no implemented control falls through to these defaults.
    """

    def describe(self) -> LaneDescribe:  # pragma: no cover - concrete lanes override
        raise NotImplementedError

    def _unsupported(self, operation: str) -> HarnessUnsupported:
        describe = self.describe()
        return HarnessUnsupported(
            operation, describe.lane_profile, describe.controls.get(operation, "unsupported")
        )

    async def prepare(self, request: PrepareRequest) -> PreparedSession:
        raise self._unsupported("prepare")

    async def start(self, request: StartRequest) -> SessionHandle:
        raise self._unsupported("start")

    async def reattach(self, request: ReattachRequest) -> SessionHandle:
        raise self._unsupported("reattach")

    async def send_turn(self, request: SendTurnRequest) -> TurnHandle:
        raise self._unsupported("send_turn")

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt:
        raise self._unsupported("cancel_turn")

    def observe(self, request: ObserveRequest) -> AsyncIterator[LaneFrame]:
        raise self._unsupported("observe")

    async def snapshot(self, request: SnapshotRequest) -> SnapshotManifest:
        raise self._unsupported("snapshot")

    async def usage(self, request: UsageRequest) -> UsageReport:
        raise self._unsupported("usage")

    async def end_session(self, request: EndSessionRequest) -> CleanupReceipt:
        raise self._unsupported("end_session")


DEFAULT_STUBS = {
    name: getattr(UnsupportedHarnessOperations, name)
    for name in HARNESS_PROTOCOL_METHODS
    if name != "describe"
}


def implements(harness: object, operation: str) -> bool:
    """True when `harness` overrides `operation` instead of inheriting the unsupported stub."""

    implementation = getattr(type(harness), operation, None)
    return implementation is not None and implementation is not DEFAULT_STUBS.get(operation)


__all__ = [
    "DEFAULT_STUBS",
    "HARNESS_PROTOCOL_METHODS",
    "AgentHarness",
    "HarnessUnsupported",
    "NativeRunUsageLane",
    "NativeTurnLost",
    "OperationLane",
    "SessionLane",
    "UnsupportedHarnessOperations",
    "ValidatesOperationRequest",
    "WorkspaceLeasingLane",
    "implements",
]
