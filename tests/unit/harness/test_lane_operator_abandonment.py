"""Protocol lane operator decisions never become fabricated native acknowledgement."""

from __future__ import annotations

import pytest

from mission_control.application.execution.harness.dispatch import (
    SessionOwnedElsewhere,
)
from mission_control.application.execution.harness.lane_turns import (
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.domain.execution.lane_turns import LaneCancelRequest, LaneCleanupRequest
from tests.support.unit.harness.lane_operator_abandonment import lane_recovery, no_adapter_selection
from tests.support.unit.operations.lane_reconciliation import NativeRecovery


def cancel_request(recovery: NativeRecovery):
    return LaneCancelRequest(
        operation=recovery.request, lane_profile="claude_agent_sdk", generation=1
    )


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
