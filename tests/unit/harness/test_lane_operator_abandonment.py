"""Protocol lane operator decisions never become fabricated native acknowledgement."""

from __future__ import annotations

from datetime import timedelta

import pytest

from mission_control.application.execution.harness.dispatch import (
    DispatchRecord,
    SessionOwnedElsewhere,
)
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.domain.execution.lane_turns import LaneCancelRequest, LaneCleanupRequest
from tests.fixtures.lane_turns import lane_stack
from tests.unit.harness.test_lane_cleanup import CleaningLane
from tests.unit.operations.test_lane_reconciliation import NativeRecovery, native_recovery


async def lane_recovery(owner="worker:operator-recovery"):
    recovery = await native_recovery()
    lane = CleaningLane(describe_matrix=recovery.lane.describe_matrix)
    local = lane_stack(lane, operation=recovery.request)
    service = LaneTurnService(
        lanes=local.service._lanes,
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


def cancel_request(recovery: NativeRecovery):
    return LaneCancelRequest(
        operation=recovery.request, lane_profile="claude_agent_sdk", generation=1
    )


def no_adapter_selection(*args, **kwargs):
    raise AssertionError("operator recovery must precede every adapter selection/call")


async def test_ambiguous_create_records_real_incident_before_any_adapter_selection(monkeypatch):
    recovery, service, local, lane, identity = await lane_recovery()
    monkeypatch.setattr(service, "_session_lane", no_adapter_selection)
    result = await service.cancel(
        cancel_request(recovery), attempt=recovery.harness.attempt(recovery.request)
    )
    assert not result.settled
    assert not result.receipt.acknowledged and not result.receipt.already_terminal
    assert result.receipt.native_status == "unknown"
    incident = await recovery.incident()
    assert (
        incident is not None
        and incident.reason == "ambiguous_native_effect"
        and incident.namespace is None
    )
    assert not lane.calls and not lane.cleanups
    state = await local.states.load(identity.request_scope, identity.harness_execution_id)
    assert next(iter(state.dispatches.values())).phase == "in_doubt"
    assert state.native_session_ref is None and state.native_turn_ref is None


async def test_abandon_and_repeated_cancel_preserve_honest_unknown_native_receipt(monkeypatch):
    recovery, service, local, lane, identity = await lane_recovery()
    await recovery.reconcile(reason="create_dispatch_ambiguous")
    await recovery.abandon()
    monkeypatch.setattr(service, "_session_lane", no_adapter_selection)
    first = await service.cancel(
        cancel_request(recovery), attempt=recovery.harness.attempt(recovery.request)
    )
    second = await service.cancel(
        cancel_request(recovery), attempt=recovery.harness.attempt(recovery.request)
    )
    for result in (first, second):
        assert result.settled
        assert result.operation_result["failure_code"] == "in_doubt_abandoned"
        assert result.receipt.native_status == "unknown"
        assert not result.receipt.acknowledged and not result.receipt.already_terminal
    assert first.operation_result == second.operation_result
    assert len(recovery.harness.journal.settlements) == 1
    assert not lane.calls and not lane.cleanups
    assert all(
        call.args[3] != "provider_acknowledged"
        for call in recovery.milestones.record_milestone.await_args_list
    )
    state = await local.states.load(identity.request_scope, identity.harness_execution_id)
    assert next(iter(state.dispatches.values())).phase == "in_doubt"


async def test_cleanup_retains_unresolved_native_evidence_after_operator_abandonment():
    recovery, service, local, lane, identity = await lane_recovery()
    await recovery.reconcile(reason="create_dispatch_ambiguous")
    await recovery.abandon()
    await service.cancel(
        cancel_request(recovery), attempt=recovery.harness.attempt(recovery.request)
    )
    assert await recovery.harness.service.lane_settlement(recovery.request) is not None
    outcome = await service.cleanup(
        LaneCleanupRequest(
            operation=recovery.request, lane_profile="claude_agent_sdk", generation=1
        )
    )
    assert outcome.outcome == "retained" and outcome.reason_code == "native_dispatch_unresolved"
    assert lane.cleanups == []
    state = await local.states.load(identity.request_scope, identity.harness_execution_id)
    assert next(iter(state.dispatches.values())).phase == "in_doubt"


async def test_foreign_live_session_owner_cannot_produce_or_apply_operator_decision():
    recovery, _service, local, lane, _identity = await lane_recovery(owner="worker:original-owner")
    foreign = LaneTurnService(
        lanes=local.service._lanes,
        boundary=recovery.harness.service,
        frames=local.frames,
        states=local.states,
        sessions=WorkerSessionManager(owner_ref="worker:foreign-owner"),
        clock=recovery.harness.clock,
    )
    with pytest.raises(SessionOwnedElsewhere):
        await foreign.cancel(
            cancel_request(recovery), attempt=recovery.harness.attempt(recovery.request)
        )
    assert await recovery.incident() is None
    assert not recovery.harness.journal.settlements and not lane.calls


async def test_no_activity_attempt_keeps_legacy_ambiguity_without_fabricated_incident(monkeypatch):
    recovery, service, _local, lane, _identity = await lane_recovery()
    monkeypatch.setattr(service, "_session_lane", no_adapter_selection)
    result = await service.cancel(cancel_request(recovery))
    assert not result.settled and result.receipt.native_status == "unknown"
    assert await recovery.incident() is None
    assert not recovery.harness.journal.settlements and not lane.calls


async def test_control_only_cancel_does_not_apply_accepted_abandonment_or_settle(monkeypatch):
    recovery, service, _local, lane, _identity = await lane_recovery()
    await recovery.reconcile(reason="create_dispatch_ambiguous")
    await recovery.abandon()
    monkeypatch.setattr(service, "_session_lane", no_adapter_selection)
    result = await service.cancel(
        cancel_request(recovery).model_copy(update={"settle": False}),
        attempt=recovery.harness.attempt(recovery.request),
    )
    assert not result.settled and not result.receipt.acknowledged
    assert result.receipt.native_status == "unknown"
    assert not recovery.harness.journal.settlements and not lane.calls
    assert await recovery.harness.service.lane_settlement(recovery.request) is None
