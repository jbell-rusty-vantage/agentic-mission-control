"""Real in-memory authority regression for protocol-lane operator abandonment.

No CLI, model, network, database or Temporal service is started by these tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.execution.operations.journaled_operation_execution import (
    _effect_claim_id,
)
from mission_control.application.execution.operations.operation_execution import (
    OperationExecutionInProgress,
    RunControlOperationAuthority,
    bind_operation_execution_request,
    operation_settlement_id,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.checkpoint_lineage import (
    CheckpointLineageConflict,
    UnitResultObservation,
    unit_result_observation_id,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationSettlement,
    RuntimeUsage,
)
from mission_control.domain.policies.contracts import (
    CancelAction,
    ClaimEffectAction,
    CommandStatus,
    ReconcileUnitAction,
)
from tests.fixtures.checkpoint_recovery import (
    FixtureControlPlane,
    RecoveryHarness,
    SimulatedWorkerCrash,
    recovery_harness,
    stage_recovery_unit,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import ScriptedSessionLane
from tests.unit.claude.fixtures import claude_operation
from tests.unit.run_control.test_run_control import command, reconciler_command


@dataclass
class NativeRecovery:
    harness: RecoveryHarness
    request: OperationExecutionRequest
    lane: ScriptedSessionLane
    milestones: AsyncMock
    decisions: dict = field(default_factory=dict)

    @property
    def binding(self):
        return bind_operation_execution_request(self.request)

    async def incident(self):
        return await self.harness.lineage.get_incident(
            self.request.request_scope, self.request.runtime_unit.unit_key, 1
        )

    async def reconcile(self, *, reason=None, attempt=None):
        return await self.harness.service.reconcile_lane_cancellation(
            self.request,
            attempt=attempt or self.harness.attempt(self.request),
            reason=reason,
        )

    async def abandon(self, decision_id="abandon-native-uncertainty"):
        incident = await self.incident()
        assert incident is not None
        if decision_id not in self.decisions:
            run = await self.harness.run_control.get_run(
                self.request.request_scope, self.harness.run_id
            )
            self.decisions[decision_id] = reconciler_command(
                self.harness.run_id,
                run.version,
                decision_id,
                ReconcileUnitAction(
                    unit_key=incident.unit_key,
                    execution_generation=incident.execution_generation,
                    incident_id=incident.incident_id,
                    decision="abandon_unit",
                ),
            )
        return await self.harness.reconciliation.reconcile_unit(self.decisions[decision_id])


async def native_recovery() -> NativeRecovery:
    harness = await recovery_harness(real_authority=True)
    unit = stage_recovery_unit(harness.run_id)
    reserved = await harness.request(unit)
    claude = claude_operation()
    request = OperationExecutionRequest.model_validate(
        {
            **reserved.model_dump(mode="python"),
            "execution_runtime": "claude",
            "lane_profile": "claude_agent_sdk",
            **lane_fields(None),
            "native_placement": None,
            **lane_fields(ProviderExecutionBinding.carried_by(claude)),
        }
    )
    from mission_control.adapters.claude.describe import CLAUDE_AGENT_SDK_DESCRIBE

    lane = ScriptedSessionLane(describe_matrix=CLAUDE_AGENT_SDK_DESCRIBE)
    harness.service._lanes = LaneRegistry(
        [DeepAgentsHarness(harness.runtime), lane], allow_unqualified=True
    )
    harness.service._authority = RunControlOperationAuthority(
        harness.run_control, FixtureControlPlane(request)
    )
    milestones = AsyncMock()
    harness.service._stop_fences = milestones
    await harness.service.admit_lane_session(request, attempt=harness.attempt(request))
    run = await harness.run_control.get_run(request.request_scope, harness.run_id)
    cancelled = await harness.run_control.execute(
        command(harness.run_id, run.version, "cancel-native-fixture", CancelAction())
    )
    assert cancelled.status == CommandStatus.ACCEPTED
    return NativeRecovery(harness, request, lane, milestones)


async def test_real_non_deep_attempt_produces_one_genuine_incident_without_provider_work():
    stack = await native_recovery()
    assert await stack.reconcile() is None, "no incident means no manufactured operator decision"
    first = await stack.reconcile(reason="create_dispatch_ambiguous")
    second = await stack.reconcile(reason="create_dispatch_ambiguous")
    assert first.status == second.status == "in_doubt"
    incident = await stack.incident()
    assert incident is not None
    assert incident.reason == "ambiguous_native_effect"
    assert incident.namespace is None and not incident.candidates
    assert incident.belllabs_run_id == stack.harness.run_id
    assert incident.binding_id == stack.binding.binding_id
    assert (
        first.reconciliation_incident_id
        == second.reconciliation_incident_id
        == incident.incident_id
    )
    assert len(stack.harness.lineage.incident_history) == 1
    assert not stack.lane.calls and not stack.harness.model.calls
    assert not stack.harness.journal.settlements


async def test_normal_abandon_decision_and_settlement_replay_preserve_unknown_usage():
    stack = await native_recovery()
    await stack.reconcile(reason="create_dispatch_ambiguous")
    decision = await stack.abandon()
    assert decision.status == CommandStatus.ACCEPTED
    settled = await stack.reconcile()
    assert settled.status == "cancelled" and settled.failure_code == "in_doubt_abandoned"
    assert "unknown" in settled.failure_message.lower()
    assert await stack.reconcile() == settled
    replay = await stack.abandon()
    assert replay.status == CommandStatus.ACCEPTED
    assert await stack.reconcile() == settled
    incident = await stack.incident()
    assert incident.status == "resolved" and incident.decision == "abandon_unit"
    assert len(stack.harness.lineage.incident_history) == 1
    [journal] = list(stack.harness.journal.settlements.values())
    assert journal.usage == {}, "no attribution is different from a zero-token provider fact"
    settlement = await stack.harness.service._get_settlement(stack.binding)
    assert {
        "operator_abandonment": {
            "incident_id": incident.incident_id,
            "decision_id": "abandon-native-uncertainty",
            "native_status": "unknown",
            "usage_disposition": "unknown",
            "provider_acknowledged": False,
        }
    } in settlement.event_payloads
    budget = await stack.harness.run_control.get_budget(
        stack.request.request_scope, stack.harness.run_id
    )
    assert stack.request.budget_reservation_id not in budget.reservations
    assert not any(budget.consumed.values()), "budget projection has no attributed usage"
    assert not stack.lane.calls and not stack.harness.model.calls
    assert all(
        call.args[3] != "provider_acknowledged"
        for call in stack.milestones.record_milestone.await_args_list
    )


async def test_unsettled_consequential_effect_is_not_settled_over_by_abandonment():
    stack = await native_recovery()
    run = await stack.harness.run_control.get_run(stack.request.request_scope, stack.harness.run_id)
    claimed = await stack.harness.run_control.execute(
        command(
            stack.harness.run_id,
            run.version,
            "claim-unresolved-native-consequence",
            ClaimEffectAction(
                effect_id="tool-effect:unknown-native-consequence",
                effect_kind="tool.consequential",
                operation_ref=stack.binding.binding_id,
                provider_idempotency_key="tool-effect:unknown-native-consequence",
                reservation_id=stack.request.budget_reservation_id,
            ),
        )
    )
    assert claimed.status == CommandStatus.ACCEPTED
    await stack.reconcile(reason="create_dispatch_ambiguous")
    await stack.abandon()
    result = await stack.reconcile()
    assert result.status == "in_doubt"
    assert not stack.harness.journal.settlements
    effects = await stack.harness.run_control.get_effects(
        stack.request.request_scope, stack.harness.run_id
    )
    assert effects.claims["tool-effect:unknown-native-consequence"].settlement is None
    assert effects.claims[_effect_claim_id(stack.binding)].settlement is None
    assert not stack.lane.calls
    assert all(
        call.args[3] != "provider_acknowledged"
        for call in stack.milestones.record_milestone.await_args_list
    )


async def test_active_attempt_holder_refuses_competing_incident_and_late_result_is_fenced():
    stack = await native_recovery()
    lineage = CheckpointLineageService(stack.harness.lineage, clock=stack.harness.clock)
    owner_attempt = stack.harness.attempt(stack.request, lease=timedelta(seconds=5))
    owner = await lineage.admit_attempt(stack.binding, owner_attempt)
    assert owner.admission.lease_granted
    with pytest.raises(OperationExecutionInProgress):
        await stack.reconcile(reason="create_dispatch_ambiguous")
    assert await stack.incident() is None
    stack.harness.clock.advance(timedelta(seconds=6))
    await stack.reconcile(reason="create_dispatch_ambiguous")
    await stack.abandon()
    settled = await stack.reconcile()
    assert settled.status == "cancelled"
    stale = UnitResultObservation(
        observation_id=unit_result_observation_id(
            stack.request.request_scope, stack.request.runtime_unit.unit_key, 1
        ),
        request_scope=stack.request.request_scope,
        unit_key=stack.request.runtime_unit.unit_key,
        execution_generation=1,
        claim_fence=owner.fence,
        binding_id=stack.binding.binding_id,
        settlement_id="late-old-native-result",
        status="completed",
        result_manifest_ref="late-result-fixture",
        result_manifest_digest="sha256:" + "d" * 64,
        result_manifest_size_bytes=1,
        observed_at=stack.harness.clock(),
    )
    with pytest.raises(CheckpointLineageConflict):
        await stack.harness.lineage.record_result(stale)
    assert await stack.reconcile() == settled
    assert len(stack.harness.journal.settlements) == 1
    assert not stack.lane.calls


async def test_existing_fenced_result_manifest_wins_over_new_native_ambiguity_reason(monkeypatch):
    stack = await native_recovery()
    lineage = CheckpointLineageService(stack.harness.lineage, clock=stack.harness.clock)
    attempt = stack.harness.attempt(stack.request, lease=timedelta(seconds=5))
    admitted = await lineage.admit_attempt(stack.binding, attempt)
    settlement = OperationSettlement(
        settlement_id=operation_settlement_id(stack.binding.binding_id),
        binding_id=stack.binding.binding_id,
        status="cancelled",
        usage=RuntimeUsage(amounts={"tokens.total": 3}),
        settled_at=stack.harness.clock(),
    )
    original = stack.harness.coordinator.settle

    async def crash_after_fenced_manifest(*args, before_authority=None, **kwargs):
        assert before_authority is not None

        async def observed_then_crash(*address):
            await before_authority(*address)
            raise SimulatedWorkerCrash

        return await original(*args, before_authority=observed_then_crash, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(stack.harness.coordinator, "settle", crash_after_fenced_manifest)
        with pytest.raises(SimulatedWorkerCrash):
            await stack.harness.service._settle(
                stack.binding,
                stack.harness.journal.claims[_effect_claim_id(stack.binding)],
                settlement,
                started_at=stack.harness.clock(),
                attempt=attempt,
                admitted=admitted,
            )
    assert not stack.harness.journal.settlements
    stack.harness.clock.advance(timedelta(seconds=6))
    result = await stack.reconcile(reason="create_dispatch_ambiguous")
    assert result.status == "cancelled" and result.failure_code != "in_doubt_abandoned"
    assert await stack.incident() is None
    [recorded] = list(stack.harness.journal.settlements.values())
    assert recorded.usage == {"tokens.total": 3}
    assert not stack.lane.calls and not stack.harness.model.calls
