"""Actual scoped PG admission, lineage, native dispatch and atomic operator settlement.

The provider is forbidden. Artifact bytes and immutable binding lookup remain labelled
in-memory fixtures; authority, lineage, operation journal and lane state use the disposable
common database. This does not claim a fully persistent artifact/binding composition.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.claude.describe import CLAUDE_AGENT_SDK_DESCRIBE
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.postgres.operations.operation_journal import (
    PostgresAtomicOperationJournalRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.execution.harness.dispatch import DispatchRecord
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
    execution_start,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    RunControlOperationAuthority,
    bind_operation_execution_request,
)
from mission_control.application.execution.operations.operation_journal import (
    OperationJournalService,
)
from mission_control.application.execution.operations.unit_reconciliation import (
    UnitReconciliationService,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import LaneCancelRequest, LaneCleanupRequest
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    ReconcileUnitAction,
)
from tests.fixtures.checkpoint_recovery import (
    FixtureControlPlane,
    recovery_harness,
    stage_recovery_unit,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.claude.fixtures import claude_operation
from tests.unit.harness.test_lane_cleanup import CleaningLane
from tests.unit.harness.test_lane_operator_abandonment import no_adapter_selection
from tests.unit.run_control.test_run_control import actor, command, reconciler_command
from tests.unit.run_control.test_run_control import service as run_control_service

pytestmark = pytest.mark.common_db


async def test_persisted_protocol_incident_normal_abandonment_and_unknown_settlement(
    common_db: CommonDatabase, monkeypatch
):
    pool = await common_db.pool("mission_control_runtime")
    try:
        run_control, _ = run_control_service(PostgresRunControlRepository(pool))
        scope = common_db.scope()
        harness = await recovery_harness(
            run_control=run_control, request_scope=scope, real_authority=True
        )
        lineage = PostgresCheckpointLineageRepository(pool)
        harness.lineage = lineage
        harness.service._lineage = CheckpointLineageService(lineage, clock=harness.clock)
        harness.reconciliation = UnitReconciliationService(run_control=run_control, lineage=lineage)
        coordinator = JournaledOperationExecutionCoordinator(
            journal=OperationJournalService(PostgresAtomicOperationJournalRepository(pool)),
            run_control=run_control,
            results=harness.results,
            actor=actor(),
        )
        harness.coordinator = coordinator
        harness.service._journal = coordinator
        unit = stage_recovery_unit(harness.run_id, request_scope=scope)
        reserved = await harness.request(unit)
        request = OperationExecutionRequest.model_validate(
            {
                **reserved.model_dump(mode="python"),
                "execution_runtime": "claude",
                "lane_profile": "claude_agent_sdk",
                **lane_fields(None),
                "native_placement": None,
                **lane_fields(ProviderExecutionBinding.carried_by(claude_operation())),
            }
        )
        lane = CleaningLane(describe_matrix=CLAUDE_AGENT_SDK_DESCRIBE)
        registry = LaneRegistry([lane], allow_unqualified=True)
        harness.service._lanes = registry
        harness.service._authority = RunControlOperationAuthority(
            run_control, FixtureControlPlane(request)
        )
        milestones = AsyncMock()
        harness.service._stop_fences = milestones
        await harness.service.admit_lane_session(request, attempt=harness.attempt(request))
        run = await run_control.get_run(scope, harness.run_id)
        accepted = await run_control.execute(
            command(harness.run_id, run.version, "pg-native-cancel", CancelAction()).model_copy(
                update={"request_scope": scope}
            )
        )
        assert accepted.status == CommandStatus.ACCEPTED
        frames = PostgresFrameRepository(pool)
        states = PostgresLaneExecutionStateStore(pool)
        service = LaneTurnService(
            lanes=registry,
            boundary=harness.service,
            frames=frames,
            states=states,
            sessions=WorkerSessionManager(owner_ref="pg-native-owner"),
            clock=harness.clock,
        )
        monkeypatch.setattr(service, "_session_lane", no_adapter_selection)
        identity = LaneExecutionIdentity.of(request, "claude_agent_sdk", 1)
        # Match production's pre-native frame identity; this is not a provider receipt.
        await frames.open_execution(
            execution_start(request, identity, 1, str(identity.harness_execution_id))
        )
        owner = await states.claim_owner(
            scope,
            identity.harness_execution_id,
            owner_ref="pg-native-owner",
            generation=1,
            now=harness.clock(),
            lease=timedelta(minutes=1),
        )
        dispatch = DispatchRecord(
            kind="create",
            idempotency_key=f"{identity.harness_execution_id}:1:turn:1",
            expected_generation=1,
            instruction_digest="sha256:" + "a" * 64,
            owner_ref=owner.owner_ref,
            owner_epoch=owner.epoch,
            intended_at=harness.clock(),
        )
        await states.intend_dispatch(scope, identity.harness_execution_id, dispatch, owner=owner)
        await states.resolve_dispatch(
            scope,
            identity.harness_execution_id,
            "create",
            dispatch.idempotency_key,
            outcome="in_doubt",
            owner=owner,
            at=harness.clock(),
            reason="create_dispatch_ambiguous",
        )
        cancel = LaneCancelRequest(operation=request, lane_profile="claude_agent_sdk", generation=1)
        parked = await service.cancel(cancel, attempt=harness.attempt(request))
        assert not parked.settled and not parked.receipt.acknowledged
        # Reload through an independent repository, proving this is actual PG evidence.
        incident = await PostgresCheckpointLineageRepository(pool).get_incident(
            scope, unit.unit_key, 1
        )
        assert (
            incident is not None
            and incident.reason == "ambiguous_native_effect"
            and incident.namespace is None
        )
        run = await run_control.get_run(scope, harness.run_id)
        decision_command = reconciler_command(
            harness.run_id,
            run.version,
            "pg-operator-abandon",
            ReconcileUnitAction(
                unit_key=unit.unit_key,
                execution_generation=1,
                incident_id=incident.incident_id,
                decision="abandon_unit",
            ),
        ).model_copy(update={"request_scope": scope})
        assert (
            await harness.reconciliation.reconcile_unit(decision_command)
        ).status == CommandStatus.ACCEPTED
        settled = await service.cancel(cancel, attempt=harness.attempt(request))
        assert settled.settled and settled.receipt.native_status == "unknown"
        assert not settled.receipt.acknowledged and not settled.receipt.already_terminal
        assert (
            await harness.reconciliation.reconcile_unit(decision_command)
        ).status == CommandStatus.ACCEPTED
        repeated = await service.cancel(cancel, attempt=harness.attempt(request))
        assert repeated == settled
        binding = bind_operation_execution_request(request)
        actual = await coordinator.get_settlement(binding)
        assert actual.usage.amounts == {}
        assert actual.event_payloads == (
            {
                "operator_abandonment": {
                    "incident_id": incident.incident_id,
                    "decision_id": "pg-operator-abandon",
                    "native_status": "unknown",
                    "usage_disposition": "unknown",
                    "provider_acknowledged": False,
                }
            },
        )
        state = await PostgresLaneExecutionStateStore(pool).load(
            scope, identity.harness_execution_id
        )
        assert state.dispatch("create", dispatch.idempotency_key).phase == "in_doubt"
        cleanup = await service.cleanup(
            LaneCleanupRequest(operation=request, lane_profile="claude_agent_sdk", generation=1)
        )
        assert cleanup.reason_code == "native_dispatch_unresolved" and not lane.cleanups
        assert not lane.calls and not harness.model.calls
        assert all(
            c.args[3] != "provider_acknowledged"
            for c in milestones.record_milestone.await_args_list
        )
    finally:
        await pool.close()
