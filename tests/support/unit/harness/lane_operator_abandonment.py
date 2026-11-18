"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_lane_operator_abandonment.py.
"""

from __future__ import annotations

from datetime import timedelta

from mission_control.application.execution.harness.dispatch import DispatchRecord
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.resolution.registries import LaneRegistry
from tests.support.lanes import lane_stack
from tests.support.unit.harness.lane_cleanup import CleaningLane
from tests.support.unit.operations.lane_reconciliation import native_recovery


class AdapterSelectionForbidden(LaneRegistry):
    """A lane registry whose admission fails the test: operator recovery must precede every
    adapter selection. Profile lookup (`for_profile`, `describe`) still answers."""

    def admit(self, lane_profile: str) -> AgentHarness:
        raise AssertionError("operator recovery must precede every adapter selection/call")


async def lane_recovery(owner="worker:operator-recovery", *, adapter_selection=True):
    """`adapter_selection=False` composes the turn service over `AdapterSelectionForbidden`."""

    recovery = await native_recovery()
    lane = CleaningLane(describe_matrix=recovery.lane.describe_matrix)
    local = lane_stack(lane, operation=recovery.request)
    lanes = (
        local.service._lanes
        if adapter_selection
        else AdapterSelectionForbidden([lane], allow_unqualified=True)
    )
    service = LaneTurnService(
        lanes=lanes,
        boundary=recovery.harness.service,
        frames=local.frames,
        states=local.states,
        sessions=WorkerSessionManager(owner_ref=owner),
        clock=recovery.harness.clock,
    )
    identity = LaneExecutionIdentity.of(recovery.request, "claude_agent_sdk", 1)
    holder = await local.states.claim_owner(
        identity.request_scope,
        identity.harness_execution_id,
        owner_ref=owner,
        generation=1,
        now=recovery.harness.clock(),
        lease=timedelta(minutes=1),
    )
    record = DispatchRecord(
        kind="create",
        idempotency_key=f"{identity.harness_execution_id}:1:turn:1",
        expected_generation=1,
        instruction_digest="sha256:" + "a" * 64,
        owner_ref=holder.owner_ref,
        owner_epoch=holder.epoch,
        intended_at=recovery.harness.clock(),
    )
    await local.states.intend_dispatch(
        identity.request_scope, identity.harness_execution_id, record, owner=holder
    )
    await local.states.resolve_dispatch(
        identity.request_scope,
        identity.harness_execution_id,
        record.kind,
        record.idempotency_key,
        outcome="in_doubt",
        owner=holder,
        at=recovery.harness.clock(),
        reason="create_dispatch_ambiguous",
    )
    return recovery, service, local, lane, identity
