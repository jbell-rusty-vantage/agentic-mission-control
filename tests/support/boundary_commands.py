"""Boundary-command builders and scripted transports, from test_boundary_commands/_interventions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mission_control.application.execution.boundary_interventions import BoundaryDeliveryResult
from mission_control.domain.policies.contracts import (
    ApplyBoundaryCommandAction,
    BoundaryCommandReceipt,
    BoundaryCommandStatus,
    CommandStatus,
    ExecutionTarget,
    LifecycleCommand,
    PauseAction,
    PauseDecision,
    ReceiptState,
    ResumeAction,
    ResumeDecision,
    SatisfyWaitAction,
    StartAction,
    WaitCondition,
)
from tests.support.run_control import ALL_PERMISSIONS, NOW, actor, command, request

FAMILY_WORKFLOW_ID = "family/run-boundary/1"
ROOT_WORKFLOW_ID = "belllabs-run/run-boundary"
TARGET = ExecutionTarget(
    family="GoalDirected",
    family_workflow_id=FAMILY_WORKFLOW_ID,
    root_workflow_id=ROOT_WORKFLOW_ID,
    execution_epoch=1,
)
BOUNDARY_PERMISSIONS = ALL_PERMISSIONS | {"workflow_run.apply_boundary_command"}


def pause(decision_id: str = "pause-1", *, runnable: bool = False) -> PauseAction:
    return PauseAction(
        decision=PauseDecision(
            decision_id=decision_id,
            scope=frozenset({"run"}),
            reason="operator hold",
            authority_ref="authority:lifecycle",
        ),
        runnable_work_remains=runnable,
    )


def resume(pause_decision_id: str = "pause-1", decision_id: str = "resume-1") -> ResumeAction:
    return ResumeAction(
        decision=ResumeDecision(
            decision_id=decision_id,
            pause_decision_id=pause_decision_id,
            reason="operator release",
            authority_ref="authority:lifecycle",
        )
    )


def declared_wait(condition_id: str = "stagegraph-wait:release") -> WaitCondition:
    return WaitCondition(
        condition_id=condition_id,
        kind="approval",
        scope=frozenset({"workflow:graph"}),
        verification_ref=f"stagegraph-wait:{condition_id}",
        timeout_policy_ref="timeout:none",
    )


def boundary_command(
    run_id: str, version: int, command_id: str, action: object, **extra: object
) -> LifecycleCommand:
    """The family boundary's command: the orchestration identity, not the operator's."""

    return command(run_id, version, command_id, action, **extra).model_copy(
        update={
            "actor": actor().model_copy(
                update={
                    "actor_id": "orchestration-authority",
                    "authority_refs": frozenset({"orchestration-authority"}),
                    "permissions": BOUNDARY_PERMISSIONS,
                }
            ),
            "idempotency_issuer": "goal-directed-worker",
        }
    )


def apply(
    command_id: str,
    action: PauseAction | ResumeAction | SatisfyWaitAction,
    *,
    runnable: bool = False,
    boundary_ref: str = FAMILY_WORKFLOW_ID,
    reservation: dict[str, int] | None = None,
    state: dict[str, object] | None = None,
) -> ApplyBoundaryCommandAction:
    return ApplyBoundaryCommandAction(
        command_id=command_id,
        command_issuer="operator",
        action=action,
        boundary_ref=boundary_ref,
        runnable_work_remains=runnable,
        resume_reservation=reservation or {},
        boundary_state=state or {},
    )


def states(status: BoundaryCommandStatus) -> list[str]:
    return [item.state.value for item in status.receipts]


def delivered(status: BoundaryCommandStatus) -> BoundaryCommandReceipt:
    return BoundaryCommandReceipt(
        command_id=status.command.command_id,
        idempotency_issuer=status.command.idempotency_issuer,
        run_id=status.command.run_id,
        request_scope=status.command.request_scope,
        ordinal=1,
        state=ReceiptState.DELIVERED,
        recorded_by="delivery-service",
        transport_ref=f"{FAMILY_WORKFLOW_ID}@segment:1",
        recorded_at=NOW,
    )


async def started(run_service, request_id: str, target: ExecutionTarget | None):  # type: ignore[no-untyped-def]
    admitted = await run_service.admit(request(request_id=request_id))
    assert admitted.run_id is not None
    started = await run_service.execute(
        command(admitted.run_id, 1, "start", StartAction(execution_target=target))
    )
    assert started.status == CommandStatus.ACCEPTED
    return admitted.run_id


class ScriptedTransport:
    """A transport that records deliveries and follows a per-command script."""

    def __init__(self, script: dict[str, str | Exception] | None = None) -> None:
        self.script = script or {}
        self.deliveries: list[str] = []

    async def deliver(self, status: BoundaryCommandStatus) -> BoundaryDeliveryResult:
        command_id = status.command.command_id
        outcome = self.script.get(command_id, "delivered")
        if isinstance(outcome, Exception):
            raise outcome
        self.deliveries.append(command_id)
        return BoundaryDeliveryResult(outcome, f"{FAMILY_WORKFLOW_ID}@segment:1", "scripted")


async def _status(run_service, run_id: str, command_id: str) -> BoundaryCommandStatus:  # type: ignore[no-untyped-def]
    status = await run_service.get_boundary_command("tenant-1", run_id, "operator", command_id)
    assert status is not None
    return status


class ScriptedHandle:
    def __init__(self, status: str, updates: list[Any]) -> None:
        self._status = status
        self._updates = list(updates)
        self.calls: list[tuple[str, Any]] = []

    async def describe(self) -> Any:
        return SimpleNamespace(status=SimpleNamespace(name=self._status))

    async def execute_update(self, name: str, argument: Any, *, result_type: Any = None) -> Any:
        self.calls.append((name, argument))
        return self._updates.pop(0)


class ScriptedClient:
    def __init__(self, handles: dict[str, ScriptedHandle]) -> None:
        self.handles = handles

    def get_workflow_handle(self, workflow_id: str, **_: Any) -> ScriptedHandle:
        return self.handles[workflow_id]
