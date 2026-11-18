"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_lane_reconciliation.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.application.execution.operations.operation_execution import (
    RunControlOperationAuthority,
    bind_operation_execution_request,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    ReconcileUnitAction,
)
from tests.support.checkpoint_recovery import (
    FixtureControlPlane,
    RecoveryHarness,
    recovery_harness,
    stage_recovery_unit,
)
from tests.support.lane_bindings import lane_fields
from tests.support.lanes import ScriptedSessionLane
from tests.support.providers.claude import claude_operation
from tests.support.run_control import command, reconciler_command


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
