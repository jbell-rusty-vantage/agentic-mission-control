"""Lane-neutral scenario plumbing: turns, held turns, harness requests, approvals, continuation.

Everything here works through the `LaneFake` contract and the production services it
composes (lane turn service, mailbox, approval broker, continuation service); nothing reads a
particular provider. FIXTURES only: no network, no credentials, no paid call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from mission_control.application.execution.approvals import ApprovalContextState, ApprovalTaskView
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.approvals_memory import (
    InMemoryApprovalStore,
    StaticApprovalContext,
)
from mission_control.application.execution.harness.lane_turns import harness_scope
from mission_control.application.execution.harness.state import LaneExecutionState
from mission_control.application.human_tasks.memory import InMemoryHumanTaskRepository
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.domain.context.checkpoint import CheckpointIdentities
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.execution.lane_turns import LaneCancelRequest, LaneTurnResult
from mission_control.domain.execution.lanes import (
    CursorExecutionBinding,
    LaneSegmentBounds,
    SessionHandle,
)
from mission_control.domain.policies.contracts import ActorContext
from tests.conformance.lanes.contract import ContinuationPorts, LaneFake
from tests.fixtures.continuation import CONT_SCOPE, build_service, facts, seal_target, trigger
from tests.fixtures.lane_turns import SCOPE, RecordingSignals
from tests.unit.approvals.fixtures import answer

# Bounds every scenario segment runs under: short enough to fail fast, long enough for a
# fixture turn (the reattach scenario lowers `max_frames` to end a segment mid-stream).
SEGMENT = LaneSegmentBounds(
    max_frames=500,
    max_duration_s=20,
    start_to_close_s=40,
    heartbeat_timeout_s=3,
    status_poll_limit=2,
    status_poll_interval_s=1,
    busy_wait_s=10,
)
WITHIN_S = 30.0
POLL_S = 0.01
REVIEWER = "owner"
UNBOUND_POLICY = "sha256:" + "0" * 64


def binding_digest(operation: OperationExecutionRequest) -> str:
    """The digest a harness request carries (as `lane.turn` sends it)."""

    if CursorExecutionBinding.carried_by(operation) is not None:
        return CursorExecutionBinding.carried_by(operation).binding_digest
    return operation.effective_configuration_digest


def harness_fields(fake: LaneFake, key: str) -> dict[str, Any]:
    """The `HarnessRequest` fields of a direct harness call on the fake's execution."""

    identity = fake.identity
    return {
        "scope": harness_scope(identity.request_scope),
        "lane_profile": fake.profile,
        "harness_execution_id": str(identity.harness_execution_id),
        "binding_digest": binding_digest(fake.operation),
        "idempotency_key": f"{identity.harness_execution_id}:1:{key}",
        "generation": 1,
    }


def signals(fake: LaneFake, *, cancel: bool = False) -> RecordingSignals:
    return RecordingSignals(
        fake.control.lanes.frames, fake.identity.harness_execution_id, cancel=cancel
    )


async def eventually[T](probe: Callable[[], Awaitable[T]]) -> T:
    """The first truthy answer of `probe`, polled until `WITHIN_S` passes."""

    for _attempt in range(int(WITHIN_S / POLL_S)):
        if answer := await probe():
            return answer
        await asyncio.sleep(POLL_S)
    raise AssertionError(f"no answer within {WITHIN_S:g}s")


async def run_turn(fake: LaneFake, **changes: Any) -> LaneTurnResult:
    """One `lane.turn` segment, as the operation workflow schedules it."""

    request = fake.control.turn(**{"segment": SEGMENT, **changes})
    return await asyncio.wait_for(fake.control.service.turn(request, signals(fake)), WITHIN_S)


async def held_turn(fake: LaneFake, *, cancel: bool = False) -> asyncio.Task[LaneTurnResult]:
    """The first segment running in the background, once the provider holds its turn and the
    lane state records the native turn (so a control targets a recorded turn)."""

    request = fake.control.turn(segment=SEGMENT)
    task = asyncio.create_task(fake.control.service.turn(request, signals(fake, cancel=cancel)))
    await asyncio.wait_for(fake.until_held(), WITHIN_S)

    async def recorded_turn() -> str | None:
        state = await lane_state(fake)
        return state.native_turn_ref if state is not None else None

    await eventually(recorded_turn)
    return task


async def finish(task: asyncio.Task[LaneTurnResult]) -> LaneTurnResult:
    return await asyncio.wait_for(task, WITHIN_S)


async def cancel_held(fake: LaneFake, task: asyncio.Task[LaneTurnResult]) -> Any:
    """The workflow's cancel: the running segment is cancelled, then `lane.cancel` settles."""

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    return await fake.control.service.cancel(cancel_request(fake))


def cancel_request(fake: LaneFake) -> LaneCancelRequest:
    return LaneCancelRequest.model_validate(
        {"operation": fake.operation, "lane_profile": fake.profile, "generation": 1}
    )


def settled(result: Any) -> OperationExecutionResult:
    return OperationExecutionResult.model_validate(result.operation_result)


async def lane_state(fake: LaneFake) -> LaneExecutionState | None:
    identity = fake.identity
    return await fake.control.lanes.states.load(
        identity.request_scope, identity.harness_execution_id
    )


async def live_session(fake: LaneFake) -> SessionHandle:
    """The native session the lane state records for the execution."""

    state = await lane_state(fake)
    assert state is not None and state.native_session_ref is not None
    return SessionHandle(
        lane_profile=fake.describe.lane_profile,
        harness_execution_id=str(fake.identity.harness_execution_id),
        generation=1,
        native_session_ref=state.native_session_ref,
    )


def delivery_states(status: Any) -> list[str]:
    return [item.state.value for item in status.receipts]


# --- approvals ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalRig:
    """MP-11's broker and Human Task service over the in-memory FIXTURE approval stores; its
    context probe answers what PostgreSQL would once `bind` names the execution."""

    broker: ApprovalBroker
    store: InMemoryApprovalStore
    service: HumanTaskService
    context: StaticApprovalContext
    request_scope: str

    def bind(self, fake: LaneFake) -> None:
        """The execution's recorded binding digest (`harness_execution.intended_binding_digest`)
        and generation are what the broker revalidates every decision against."""

        assert fake.identity.request_scope == self.request_scope
        self.context.state = ApprovalContextState(
            generation=1, policy_digest=binding_digest(fake.operation), granted=True
        )

    async def open_task(self) -> ApprovalTaskView:
        async def opened() -> tuple[ApprovalTaskView, ...]:
            return await self.store.list_tasks(self.request_scope, lifecycle="open")

        return (await eventually(opened))[0]

    async def approve(self, task: ApprovalTaskView) -> None:
        await self.service.resolve_approval(
            task.human_task_id, answer(task, decision="approve"), ActorContext(actor_id=REVIEWER)
        )


def approval_rig(request_scope: str = SCOPE) -> ApprovalRig:
    """A broker whose probe refuses every decision until `ApprovalRig.bind`."""

    store = InMemoryApprovalStore()
    context = StaticApprovalContext(1, UNBOUND_POLICY, granted=False)
    broker = ApprovalBroker(
        store, store, probe=context, connection_ref="worker-a#1", poll_seconds=POLL_S
    )
    service = HumanTaskService(
        InMemoryHumanTaskRepository(),
        request_scope=request_scope,
        approvals=store,
        approval_wake=broker.hub,
    )
    return ApprovalRig(broker, store, service, context, request_scope)


# --- continuation ------------------------------------------------------------------------------


async def seal_and_transfer(fake: LaneFake, ports: ContinuationPorts) -> Any:
    """`request_continuation` through the continuation service: request, seal from the live
    session's workspace, transfer into a fresh session with the lane's hydrator."""

    session = await live_session(fake)
    source = session.native_session_ref
    assert source is not None
    service = build_service(snapshots=ports.snapshots, staging=ports.staging)["service"]
    transfer = await service.request(
        trigger(),
        request_scope=CONT_SCOPE,
        run_key="run-continuation-1",
        activation_key="unit-collect-1",
        logical_execution_id="logical-collect-1",
        lane_profile=fake.profile,
        source_session_ref=source,
    )
    base = facts()
    sealed = await service.seal(
        transfer.transfer_id,
        facts(
            lane_profile=fake.profile,
            identities=CheckpointIdentities(
                **{**base.identities.model_dump(), "source_agent_session_ref": source}
            ),
        ),
        seal_target(),
        request_scope=CONT_SCOPE,
    )
    assert sealed.checkpoint is not None, sealed.transfer
    return await service.transfer(transfer.transfer_id, ports.hydrator, request_scope=CONT_SCOPE)


__all__ = [
    "REVIEWER",
    "SEGMENT",
    "ApprovalRig",
    "approval_rig",
    "binding_digest",
    "cancel_held",
    "cancel_request",
    "delivery_states",
    "eventually",
    "finish",
    "harness_fields",
    "held_turn",
    "lane_state",
    "live_session",
    "run_turn",
    "seal_and_transfer",
    "settled",
    "signals",
]
