"""Shared workflow mechanics of a nested family body (OVE-176, WI-13).

A parent family (Stage Graph stage, Goal Loop executor phase) whose unit hosts a compiled
``NestedBody`` calls :func:`start_nested_body` after admitting that unit. It returns a handle the
family keeps in place of an operation child handle, and a future that resolves to the unit's
``OperationWorkflowResult``:

1. ``nested_program.activate`` admits the body's child run (deterministic per unit attempt) and
   returns its ``mc.mission_run.v1`` root input; a typed refusal fails the unit (nothing started,
   the reservation is released, the body is never flattened into an operation);
2. the child root starts as a Temporal child workflow with its own deterministic id, so a
   restart or replay re-attaches to the same child run instead of starting another;
3. when the child root ends, ``nested_program.settle`` records the exact export receipt and
   settles the unit's reservation against the child's actual usage; the unit result mirrors the
   child's terminal outcome.

Control lineage: :meth:`NestedBodyHandle.cancel` (what the family's cancellation saga calls on
every active unit) and :meth:`NestedBodyHandle.propagate` deliver the parent's cancel, pause or
resume through the child run's own run control (``nested_program.propagate``), so the child's
family runs its own saga; Temporal cancellation is the fallback only when the child cannot be
governed. A control that lands before the child started is kept and delivered on attach; a
cancel before the start never starts the child (its admitted run is closed by the settlement).
The ``REQUEST_CANCEL`` parent-close policy is the last resort when the parent workflow itself is
cancelled, terminated or times out: Temporal then requests cancellation of the child root, which
the root records as a hint only (governed cancellation goes through run control), so a child
whose parent closed abnormally is reconciled by its own run control or the operator.

Failure: an activation or settlement activity that exhausts its retries (or raises a conflict)
never escapes the unit: the unit fails typed (``nested_activation_error``), and the unit's
reservation is released by a best-effort settlement.

All of it is behind :data:`NESTED_BODY_PATCH`, reached only by blueprints that declare a nested
body (no earlier history can), so every recorded history replays unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Literal

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    CancelledError,
    ChildWorkflowError,
    TerminatedError,
)
from temporalio.exceptions import TimeoutError as TemporalTimeoutError

with workflow.unsafe.imports_passed_through():
    from mission_control.domain.authoring.nested_bodies import NestedBody
    from mission_control.domain.execution.contracts import (
        OperationWorkflowRequest,
        OperationWorkflowResult,
    )
    from mission_control.domain.programs.nested import (
        ChildEnd,
        ControlKind,
        NestedActivation,
        NestedActivationRequest,
        NestedControlReceipt,
        NestedControlRequest,
        NestedProjection,
        NestedSettlement,
        NestedSettlementRequest,
        ParentFamily,
    )

NESTED_BODY_PATCH = "oc-wi13-nested-body"
NESTED_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=16,
)

# Starts the child root (`mc.mission_run.v1`, named by type to avoid an import cycle).
ChildStarter = Callable[[Any, str], Awaitable[Any]]


def child_end(error: BaseException) -> tuple[ChildEnd, str]:
    """How a child root ended when awaiting it raised."""

    cause: BaseException | None = error.cause if isinstance(error, ChildWorkflowError) else error
    if isinstance(cause, CancelledError | asyncio.CancelledError):
        return "cancelled", "cancelled"
    if isinstance(cause, TerminatedError):
        return "terminated", "terminated"
    if isinstance(cause, TemporalTimeoutError):
        return "timed_out", "timed_out"
    message = str(cause or error)
    return "failed", message[:512]


class NestedBodyHandle:
    """Stands in for an operation child handle in a family's active-unit table."""

    def __init__(
        self,
        *,
        request_scope: str,
        parent_run_id: str,
        host_id: str,
        activity_timeout: timedelta,
    ) -> None:
        self._scope = request_scope
        self._parent_run_id = parent_run_id
        self._host_id = host_id
        self._timeout = activity_timeout
        self._child: Any | None = None
        self._child_run_id = ""
        self._cancel_requested = False
        self._cancel_task: asyncio.Future[None] | None = None
        # Controls delivered before the child started (pause/resume), in arrival order.
        self._pending: list[tuple[ControlKind, str, str]] = []
        self.control_failures: list[str] = []

    @property
    def child_run_id(self) -> str:
        return self._child_run_id

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def attach(self, child: Any, child_run_id: str) -> None:
        self._child = child
        self._child_run_id = child_run_id
        if self._cancel_requested:
            self._cancel_task = asyncio.ensure_future(self._cancel())
        elif self._pending:
            pending, self._pending = list(self._pending), []
            self._cancel_task = asyncio.ensure_future(self._deliver(pending))

    async def _deliver(self, pending: list[tuple[ControlKind, str, str]]) -> None:
        for kind, command_ref, reason in pending:
            await self.propagate(kind, command_ref, reason)

    def cancel(self) -> None:
        """Governed cancellation of the hosted child run (idempotent)."""

        if self._cancel_requested:
            return
        self._cancel_requested = True
        if self._child is not None:
            self._cancel_task = asyncio.ensure_future(self._cancel())

    async def propagate(self, kind: ControlKind, command_ref: str, reason: str) -> bool:
        """Deliver one parent control to the child run; False when it was not delivered.

        Before the child started, a pause/resume is kept and delivered on attach. A control the
        child's run control could not take (an exhausted activity) is recorded in
        ``control_failures`` with its typed reason and never fails the parent family.
        """

        if not self._child_run_id:
            if kind != "cancel":
                self._pending.append((kind, command_ref, reason))
            return False
        try:
            receipt: NestedControlReceipt = await workflow.execute_activity(
                "nested_program.propagate",
                NestedControlRequest(
                    request_scope=self._scope,
                    parent_run_id=self._parent_run_id,
                    host_id=self._host_id,
                    child_run_id=self._child_run_id,
                    kind=kind,
                    command_ref=command_ref,
                    reason=reason,
                    occurred_at=workflow.now(),
                ),
                result_type=NestedControlReceipt,
                start_to_close_timeout=self._timeout,
                retry_policy=NESTED_ACTIVITY_RETRY,
            )
        except ActivityError:
            self.control_failures.append(f"nested_control_unavailable:{kind}:{command_ref}")
            workflow.logger.warning("nested %s could not reach the child run", kind)
            return False
        if not receipt.delivered:
            self.control_failures.append(
                f"nested_control_not_delivered:{kind}:{receipt.reason_code or receipt.status}"
            )
        return receipt.delivered

    async def _cancel(self) -> None:
        delivered = await self.propagate(
            "cancel",
            f"nested-cancel:{self._parent_run_id}:{self._host_id}",
            "the parent cancelled its nested body",
        )
        if not delivered and self._child is not None and not self._child.done():
            self._child.cancel()


async def start_nested_body(
    *,
    request_scope: str,
    parent_run_id: str,
    parent_family: ParentFamily,
    host_id: str,
    body: NestedBody,
    operation: OperationWorkflowRequest,
    reservation_id: str,
    reservation: dict[str, int],
    execution_epoch: int,
    correlation_id: str,
    activity_timeout: timedelta,
    start_child: ChildStarter,
    unit_result: Callable[
        [NestedProjection], tuple[Literal["completed", "failed", "cancelled"], dict[str, Any]]
    ],
) -> tuple[NestedBodyHandle, asyncio.Future[OperationWorkflowResult]]:
    """Activate, run and settle one nested body; see the module doc."""

    handle = NestedBodyHandle(
        request_scope=request_scope,
        parent_run_id=parent_run_id,
        host_id=host_id,
        activity_timeout=activity_timeout,
    )
    semantic_attempt_id = operation.semantic_attempt_id

    async def settle(
        child_run_id: str,
        end: ChildEnd,
        result: dict[str, Any] | None,
        cause: str,
        *,
        started: bool = True,
    ) -> NestedSettlement:
        settled: NestedSettlement = await workflow.execute_activity(
            "nested_program.settle",
            NestedSettlementRequest(
                request_scope=request_scope,
                parent_run_id=parent_run_id,
                host_id=host_id,
                semantic_attempt_id=semantic_attempt_id,
                parent_reservation_id=reservation_id,
                body=body,
                child_run_id=child_run_id,
                end=end,
                family_result=result,
                occurred_at=workflow.now(),
                cause=cause,
                correlation_id=correlation_id,
                child_started=started,
                operation_id=operation.operation.identity.operation_id,
                operation_attempt=operation.operation.identity.operation_attempt,
                execution_generation=operation.execution_generation,
            ),
            result_type=NestedSettlement,
            start_to_close_timeout=activity_timeout,
            retry_policy=NESTED_ACTIVITY_RETRY,
        )
        return settled

    async def failed(child_run_id: str, cause: str) -> OperationWorkflowResult:
        """B1: a nested activity that cannot complete fails the unit typed; the reservation is
        released by a best-effort settlement (never an escaped activity error)."""

        try:
            settled = await settle(child_run_id, "failed", None, cause)
        except ActivityError:
            settled = NestedSettlement(
                projection=NestedProjection(
                    child_run_id=child_run_id,
                    position=body.position,
                    outcome="execution_failed",
                    composite_accepted=False,
                    cause=cause,
                ),
                reason_code="nested_settlement_unavailable",
            )
        return operation_result(settled)

    def operation_result(settled: NestedSettlement) -> OperationWorkflowResult:
        disposition, payload = unit_result(settled.projection)
        payload = {
            **payload,
            # The unit's reservation settlement, for a family that consumes it (Goal Loop).
            "nested_settlement": {
                "reservation_id": reservation_id,
                "usage": dict(settled.projection.actual_usage),
                "settled_run_version": settled.settled_run_version,
                "reason_code": settled.reason_code,
            },
        }
        return OperationWorkflowResult(
            semantic_attempt_id=semantic_attempt_id,
            execution_generation=operation.execution_generation,
            disposition=disposition,
            result=payload,
            message_cursor=operation.message_cursor,
            effect_frontier=operation.effect_frontier,
            active_async_child_ids=operation.active_async_child_ids,
        )

    async def run() -> OperationWorkflowResult:
        try:
            activation = await activate()
        except ActivityError:
            return await failed("", "nested_activation_error")
        if not activation.activated or activation.child_root is None:
            return await failed("", activation.reason_code or "nested_refused")
        if handle.cancel_requested:
            # B2: cancelled before the child started: it never starts; the settlement closes
            # its admitted run and records the activation's receipt.
            try:
                return operation_result(
                    await settle(
                        activation.child_run_id, "cancelled", None, "cancelled", started=False
                    )
                )
            except ActivityError:
                return await failed(activation.child_run_id, "nested_settlement_error")
        child = await start_child(activation.child_root, activation.child_workflow_id)
        handle.attach(child, activation.child_run_id)
        try:
            result = await child
        except (ChildWorkflowError, asyncio.CancelledError) as error:
            end, cause = child_end(error)
            try:
                return operation_result(await settle(activation.child_run_id, end, None, cause))
            except ActivityError:
                return await failed(activation.child_run_id, "nested_settlement_error")
        payload = result if isinstance(result, dict) else _as_dict(result)
        try:
            return operation_result(await settle(activation.child_run_id, "returned", payload, ""))
        except ActivityError:
            return await failed(activation.child_run_id, "nested_settlement_error")

    async def activate() -> NestedActivation:
        activation: NestedActivation = await workflow.execute_activity(
            "nested_program.activate",
            NestedActivationRequest(
                request_scope=request_scope,
                parent_run_id=parent_run_id,
                parent_family=parent_family,
                host_id=host_id,
                semantic_attempt_id=semantic_attempt_id,
                parent_reservation_id=reservation_id,
                parent_reservation=dict(reservation),
                body=body,
                parent_execution_epoch=execution_epoch,
                child_task_queue=workflow.info().task_queue,
                occurred_at=workflow.now(),
                correlation_id=correlation_id,
            ),
            result_type=NestedActivation,
            start_to_close_timeout=activity_timeout,
            retry_policy=NESTED_ACTIVITY_RETRY,
        )
        return activation

    return handle, asyncio.ensure_future(run())


def _as_dict(value: object) -> dict[str, Any] | None:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return None


__all__ = [
    "NESTED_BODY_PATCH",
    "NestedBodyHandle",
    "child_end",
    "start_nested_body",
]
